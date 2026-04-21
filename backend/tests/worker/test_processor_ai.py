"""Phase 5 pipeline tests for ``Phase2Processor`` with AI enabled.

Each test wires a stub AI adapter so the entire pipeline (rules → AI →
Evidence Validator → apply use case → persistence → export decision)
runs end-to-end without touching the network.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docunomnom.config import (
    AiEvidenceSettings,
    AiRefineSettings,
    AiSettings,
    AiThresholdSettings,
    ExporterSettings,
    ExternalOcrApiSettings,
    IngestionSettings,
    NetworkSettings,
    OcrmypdfSettings,
    OcrSettings,
    OllamaSettings,
    OpenAISettings,
    PathSettings,
    Settings,
    SplitterSettings,
    StorageSettings,
    WorkerSettings,
)
from docunomnom.core.models import (
    AiBackend,
    AiEvidenceRequest,
    AiMode,
    AiProposalAction,
    AiProposalRequest,
    ConfigSnapshot,
    EvidenceKind,
    File,
    Job,
    JobStatus,
    OcrBackend,
)
from docunomnom.core.ports.ai_split import AiSplitPort
from docunomnom.core.ports.ocr import OcrPageResult, OcrPort, OcrResult
from docunomnom.storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobRepository,
    create_all_for_tests,
    create_engine,
    make_session_factory,
)
from docunomnom.worker.processor import Phase2Processor, Phase2ProcessorConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdf(path: Path, *, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


class _StubOcr(OcrPort):
    def __init__(self, *, pages_text: list[str], work_dir: Path) -> None:
        self.pages_text = pages_text
        self.work_dir = work_dir

    def ocr_pdf(self, source_path: str, **_: object) -> OcrResult:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.work_dir / (Path(source_path).stem + ".ocr.pdf")
        artifact.write_bytes(Path(source_path).read_bytes())
        return OcrResult(
            pages=tuple(
                OcrPageResult(page_no=i + 1, text=t, layout={})
                for i, t in enumerate(self.pages_text)
            ),
            artifact_path=str(artifact),
        )


class _ScriptedAi(AiSplitPort):
    """Always returns the proposals it was constructed with; records calls."""

    def __init__(self, proposals: tuple[AiProposalRequest, ...]) -> None:
        self.proposals = proposals
        self.calls: int = 0

    def propose(self, **_: object) -> tuple[AiProposalRequest, ...]:
        self.calls += 1
        return self.proposals


def _settings(
    tmp_path: Path,
    *,
    backend: AiBackend = AiBackend.OLLAMA,
    mode: AiMode = AiMode.VALIDATE,
    auto_threshold: float = 0.85,
    review_below: float = 0.70,
    refine_max_changes: int = 3,
) -> Settings:
    paths = PathSettings(
        input_dir=str(tmp_path / "input"),
        output_dir=str(tmp_path / "output"),
        work_dir=str(tmp_path / "work"),
        archive_dir=str(tmp_path / "archive"),
    )
    storage = StorageSettings(
        database_url="sqlite://",
        ocr_artifact_dir=str(tmp_path / "artifacts"),
        page_text_inline_max_bytes=64_000,
    )
    return Settings(
        paths=paths,
        storage=storage,
        ingestion=IngestionSettings(),
        worker=WorkerSettings(),
        ocr=OcrSettings(
            backend=OcrBackend.OCRMYPDF,
            languages=("eng",),
            ocrmypdf=OcrmypdfSettings(),
            external_api=ExternalOcrApiSettings(),
        ),
        network=NetworkSettings(),
        splitter=SplitterSettings(
            min_pages_per_part=1,
            keyword_weight=0.6,
            layout_weight=0.2,
            page_number_weight=0.2,
            auto_export_threshold=0.65,
            keywords=("Invoice", "Vertrag"),
        ),
        exporter=ExporterSettings(
            archive_after_export=True,
            require_same_filesystem=True,
            output_basename_template="{stem}_part_{index:03d}.pdf",
            review_all_splits=False,
        ),
        ai=AiSettings(
            backend=backend,
            mode=mode,
            ollama=OllamaSettings(),
            openai=OpenAISettings(),
            thresholds=AiThresholdSettings(
                auto_export_min_confidence=auto_threshold,
                review_required_below=review_below,
            ),
            evidence=AiEvidenceSettings(min_evidences_per_proposal=1),
            refine=AiRefineSettings(
                max_boundary_shift_pages=1,
                max_changes_per_analysis=refine_max_changes,
            ),
        ),
    )


@pytest.fixture
def file_engine(tmp_path: Path) -> Iterator[Engine]:
    db = tmp_path / "phase5.sqlite3"
    eng = create_engine(f"sqlite:///{db}")
    create_all_for_tests(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def proc_session_factory(file_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(file_engine)


def _seed_job(session: Session, *, source_path: Path, sha: str) -> Job:
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="ai-snap",
            ai_backend=AiBackend.OLLAMA,
            ai_mode=AiMode.VALIDATE,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    file = SqlFileRepository(session).add(
        File(
            sha256=sha,
            original_name=source_path.name,
            size=source_path.stat().st_size,
            mtime=datetime.fromtimestamp(source_path.stat().st_mtime, tz=UTC).replace(tzinfo=None),
            source_path=str(source_path),
        )
    )
    assert file.id is not None
    job = SqlJobRepository(session).add(
        Job(
            file_id=file.id,
            status=JobStatus.PROCESSING,
            mode=AiMode.VALIDATE,
            run_key=sha[:32],
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
            lease_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=120),
        )
    )
    session.commit()
    return job


def _heartbeat() -> bool:
    return True


def _job_event_types(session_factory: sessionmaker[Session], job_id: int) -> list[str]:
    from sqlalchemy import text

    with session_factory() as s:
        return [
            row[0]
            for row in s.execute(
                text("SELECT type FROM job_events WHERE job_id = :j ORDER BY id"),
                {"j": job_id},
            )
        ]


def _ev_keyword(page: int, keyword: str) -> AiEvidenceRequest:
    return AiEvidenceRequest(
        kind=EvidenceKind.KEYWORD,
        page_no=page,
        snippet=keyword,
        payload={"keyword": keyword},
    )


# ---------------------------------------------------------------------------
# off mode → byte-for-byte equivalent to rule-only flow
# ---------------------------------------------------------------------------


def test_off_mode_short_circuits_ai_step(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=2)
    settings = _settings(tmp_path, backend=AiBackend.NONE, mode=AiMode.OFF)
    ocr = _StubOcr(
        pages_text=["Invoice ACME services\nPage 1 of 2", "Continuation"],
        work_dir=tmp_path / "ocr-stage",
    )
    ai = _ScriptedAi(proposals=())
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="a" * 64)
    assert job.id is not None
    outcome = proc(job, heartbeat=_heartbeat)
    assert outcome.status is JobStatus.COMPLETED
    assert ai.calls == 0
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_skipped" in types
    assert "ai_called" not in types


# ---------------------------------------------------------------------------
# validate mode → no boundary changes, only confirm/reject
# ---------------------------------------------------------------------------


def test_validate_mode_confirm_boosts_confidence(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=2)
    settings = _settings(
        tmp_path,
        backend=AiBackend.OLLAMA,
        mode=AiMode.VALIDATE,
        auto_threshold=0.85,
        review_below=0.50,
    )
    ocr = _StubOcr(
        pages_text=["Invoice ACME\nPage 1 of 2", "more"],
        work_dir=tmp_path / "ocr-stage",
    )
    ai = _ScriptedAi(
        proposals=(
            AiProposalRequest(
                action=AiProposalAction.CONFIRM,
                start_page=1,
                end_page=2,
                confidence=0.95,
                reason_code="ai_confirm",
                evidences=(_ev_keyword(1, "Invoice"),),
                target_proposal_id=0,
            ),
        )
    )
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="b" * 64)
    assert job.id is not None
    outcome = proc(job, heartbeat=_heartbeat)
    assert outcome.status is JobStatus.COMPLETED
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_called" not in types  # ai_called is emitted by the adapter via audit_cb
    assert "ai_proposal_accepted" in types
    assert "ai_applied" in types
    # Output produced.
    assert (tmp_path / "output" / "scan_part_001.pdf").exists()


def test_validate_mode_rejects_disallowed_add_action(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=2)
    settings = _settings(tmp_path, backend=AiBackend.OLLAMA, mode=AiMode.VALIDATE)
    ocr = _StubOcr(
        pages_text=["Invoice ACME\nPage 1 of 2", "more text"],
        work_dir=tmp_path / "ocr-stage",
    )
    ai = _ScriptedAi(
        proposals=(
            AiProposalRequest(
                action=AiProposalAction.ADD,
                start_page=2,
                end_page=2,
                confidence=0.95,
                reason_code="bad_add",
                evidences=(_ev_keyword(2, "Invoice"),),
            ),
        )
    )
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="c" * 64)
    assert job.id is not None
    proc(job, heartbeat=_heartbeat)
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_proposal_rejected" in types


# ---------------------------------------------------------------------------
# refine mode → conservative boundary adjustment
# ---------------------------------------------------------------------------


def test_refine_mode_adjust_within_budget(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=4)
    settings = _settings(
        tmp_path,
        backend=AiBackend.OLLAMA,
        mode=AiMode.REFINE,
        auto_threshold=0.50,
        review_below=0.40,
    )
    ocr = _StubOcr(
        pages_text=[
            "Invoice ACME services\nPage 1 of 4",
            "continuation a",
            "Vertrag start\nPage 1 of 2",
            "continuation b",
        ],
        work_dir=tmp_path / "ocr-stage",
    )
    # The rule splitter will produce two drafts; AI adjusts the first.
    ai = _ScriptedAi(
        proposals=(
            AiProposalRequest(
                action=AiProposalAction.ADJUST,
                start_page=1,
                end_page=2,
                confidence=0.90,
                reason_code="ai_adjust",
                evidences=(_ev_keyword(1, "Invoice"),),
                target_proposal_id=0,
            ),
        )
    )
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="d" * 64)
    assert job.id is not None
    proc(job, heartbeat=_heartbeat)
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_proposal_accepted" in types


def test_refine_mode_rejects_oversize_boundary_shift(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=4)
    settings = _settings(tmp_path, backend=AiBackend.OLLAMA, mode=AiMode.REFINE)
    ocr = _StubOcr(
        pages_text=[
            "Invoice ACME\nPage 1 of 4",
            "a",
            "Vertrag\nPage 1 of 2",
            "b",
        ],
        work_dir=tmp_path / "ocr-stage",
    )
    ai = _ScriptedAi(
        proposals=(
            AiProposalRequest(
                action=AiProposalAction.ADJUST,
                start_page=4,
                end_page=4,
                confidence=0.99,
                reason_code="too_big",
                evidences=(_ev_keyword(4, "Invoice"),),
                target_proposal_id=0,
            ),
        )
    )
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="e" * 64)
    assert job.id is not None
    proc(job, heartbeat=_heartbeat)
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_proposal_rejected" in types


# ---------------------------------------------------------------------------
# enhance mode → AI may add new proposals
# ---------------------------------------------------------------------------


def test_enhance_mode_can_add_new_proposal(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=3)
    settings = _settings(tmp_path, backend=AiBackend.OLLAMA, mode=AiMode.ENHANCE)
    ocr = _StubOcr(
        pages_text=[
            "Invoice ACME\nPage 1 of 3",
            "page two body content",
            "Invoice second one mid-document",
        ],
        work_dir=tmp_path / "ocr-stage",
    )
    ai = _ScriptedAi(
        proposals=(
            AiProposalRequest(
                action=AiProposalAction.ADD,
                start_page=3,
                end_page=3,
                confidence=0.92,
                reason_code="ai_add",
                evidences=(_ev_keyword(3, "Invoice"),),
            ),
        )
    )
    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: ai,
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="f" * 64)
    assert job.id is not None
    proc(job, heartbeat=_heartbeat)

    # Two parts in DB (the rule one + the AI-added one).
    from sqlalchemy import text

    with proc_session_factory() as s:
        proposals = s.execute(text("SELECT COUNT(*) FROM split_proposals")).scalar_one()
        parts = s.execute(text("SELECT COUNT(*) FROM document_parts")).scalar_one()
        decisions = s.execute(text("SELECT COUNT(*) FROM split_decisions")).scalar_one()
    assert proposals >= 2
    assert parts >= 2
    assert decisions >= 1  # at least the AI add was audited


# ---------------------------------------------------------------------------
# Adapter failure → conservative review fallback
# ---------------------------------------------------------------------------


def test_ai_failure_routes_everything_to_review(
    tmp_path: Path, proc_session_factory: sessionmaker[Session]
) -> None:
    inp = tmp_path / "input"
    inp.mkdir()
    src = _make_pdf(inp / "scan.pdf", pages=2)
    settings = _settings(tmp_path, backend=AiBackend.OLLAMA, mode=AiMode.REFINE)
    ocr = _StubOcr(
        pages_text=["Invoice ACME\nPage 1 of 2", "more"],
        work_dir=tmp_path / "ocr-stage",
    )

    class _BoomAi:
        def propose(self, **_: object) -> tuple[AiProposalRequest, ...]:
            from docunomnom.adapters.ai_split._schema import AiAdapterError

            raise AiAdapterError("upstream broken", code="ai_transport")

    proc = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=proc_session_factory,
            ocr_port_factory=lambda _wd, _cb: ocr,
            ai_split_port_factory=lambda _cb: _BoomAi(),
        )
    )
    with proc_session_factory() as session:
        job = _seed_job(session, source_path=src, sha="9" * 64)
    assert job.id is not None
    outcome = proc(job, heartbeat=_heartbeat)
    assert outcome.status is JobStatus.REVIEW_REQUIRED
    types = _job_event_types(proc_session_factory, job.id)
    assert "ai_failed" in types
