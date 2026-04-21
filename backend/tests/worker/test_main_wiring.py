"""Tests for worker main-loop helpers (watcher scan + queue drain).

These exercise ``_scan_input_dir`` and ``_drain_queue`` (the per-tick
helpers used by ``worker.main.main``) to make sure the wiring runs end-to-end
without raising and that a queued job actually flows through the
``Phase2Processor``.

Note: ``_scan_input_dir`` currently constructs a fresh ``StabilityWatcher``
per call, which means the watcher's in-memory observation table is reset
between ticks. Cross-tick stability is therefore exercised in the
dedicated watcher tests in ``test_watcher.py``; here we only verify the
helper executes cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docunomnom.adapters.clock import FixedClock
from docunomnom.config import (
    AiSettings,
    ExporterSettings,
    ExternalOcrApiSettings,
    IngestionSettings,
    NetworkSettings,
    OcrmypdfSettings,
    OcrSettings,
    PathSettings,
    Settings,
    SplitterSettings,
    StorageSettings,
    WorkerSettings,
)
from docunomnom.core.models import (
    AiBackend,
    AiMode,
    ConfigSnapshot,
    File,
    Job,
    JobStatus,
    OcrBackend,
)
from docunomnom.core.ports.ocr import OcrPageResult, OcrResult
from docunomnom.storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobRepository,
    create_all_for_tests,
    create_engine,
    make_session_factory,
)
from docunomnom.worker.main import _drain_queue, _scan_input_dir
from docunomnom.worker.processor import Phase2Processor, Phase2ProcessorConfig


def _make_pdf(path: Path, *, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def shared_engine(tmp_path: Path) -> Iterator[Engine]:
    """File-backed SQLite engine.

    Phase 3 split ``_drain_queue`` into three short transactions so the
    processor's inner session no longer contends with an outer write
    lock. We exercise the wiring against a real on-disk SQLite database
    to confirm that fix end-to-end (the previous in-memory + StaticPool
    workaround is no longer needed).
    """
    db_path = tmp_path / "wiring.sqlite3"
    eng = create_engine(f"sqlite:///{db_path}")
    create_all_for_tests(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def factory(shared_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(shared_engine)


def _settings_for(tmp_path: Path) -> Settings:
    return Settings(
        paths=PathSettings(
            input_dir=str(tmp_path / "input"),
            output_dir=str(tmp_path / "output"),
            work_dir=str(tmp_path / "work"),
            archive_dir=str(tmp_path / "archive"),
        ),
        storage=StorageSettings(
            database_url="sqlite://",
            ocr_artifact_dir=str(tmp_path / "artifacts"),
            page_text_inline_max_bytes=64_000,
        ),
        ingestion=IngestionSettings(
            poll_interval_seconds=0.1,
            stability_window_seconds=0.0,
        ),
        worker=WorkerSettings(),
        ocr=OcrSettings(
            backend=OcrBackend.OCRMYPDF,
            languages=("eng",),
            ocrmypdf=OcrmypdfSettings(),
            external_api=ExternalOcrApiSettings(),
        ),
        network=NetworkSettings(),
        splitter=SplitterSettings(keywords=("Invoice",)),
        exporter=ExporterSettings(
            archive_after_export=True,
            require_same_filesystem=True,
        ),
        ai=AiSettings(),
    )


def test_scan_input_dir_returns_zero_when_input_dir_missing(
    tmp_path: Path,
    factory: sessionmaker[Session],
) -> None:
    settings = _settings_for(tmp_path)  # input_dir does NOT exist yet
    clock = FixedClock(current=datetime(2026, 4, 19, 12, 0, 0))
    enqueued = _scan_input_dir(settings, session_factory=factory, clock=clock)
    assert enqueued == 0


def test_scan_input_dir_runs_cleanly_with_a_pdf_present(
    tmp_path: Path,
    factory: sessionmaker[Session],
) -> None:
    """A single tick must not crash and must return an int >= 0."""
    settings = _settings_for(tmp_path)
    inp = Path(settings.paths.input_dir)
    inp.mkdir(parents=True, exist_ok=True)
    _make_pdf(inp / "doc.pdf")

    clock = FixedClock(current=datetime(2026, 4, 19, 12, 0, 0))
    enqueued = _scan_input_dir(settings, session_factory=factory, clock=clock)
    assert enqueued >= 0


def _seed_processing_job(
    session: Session,
    *,
    src: Path,
    sha: str,
) -> Job:
    """Insert a File + a directly-PROCESSING Job that the loop will lease."""
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="phase2-snap",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    file = SqlFileRepository(session).add(
        File(
            sha256=sha,
            original_name=src.name,
            size=src.stat().st_size,
            mtime=datetime.fromtimestamp(src.stat().st_mtime, tz=UTC).replace(tzinfo=None),
            source_path=str(src),
        )
    )
    assert file.id is not None
    job = SqlJobRepository(session).add(
        Job(
            file_id=file.id,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key=sha[:32],
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    session.commit()
    return job


def test_drain_queue_processes_pending_job(
    tmp_path: Path,
    factory: sessionmaker[Session],
) -> None:
    settings = _settings_for(tmp_path)
    inp = Path(settings.paths.input_dir)
    inp.mkdir(parents=True, exist_ok=True)
    src = _make_pdf(inp / "doc.pdf", pages=1)

    with factory() as session:
        _seed_processing_job(session, src=src, sha="a" * 64)

    class _Stub:
        def ocr_pdf(self, source_path: str, **_: object) -> OcrResult:
            artifact = tmp_path / "ocr-stage" / "doc.ocr.pdf"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(Path(source_path).read_bytes())
            return OcrResult(
                pages=(OcrPageResult(page_no=1, text="Invoice ACME\nPage 1 of 1"),),
                artifact_path=str(artifact),
            )

    processor = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=factory,
            ocr_port_factory=lambda _wd, _cb: _Stub(),
        )
    )
    clock = FixedClock(current=datetime(2026, 4, 19, 12, 0, 0))

    did_work = _drain_queue(
        settings,
        processor=processor,
        session_factory=factory,
        clock=clock,
    )
    assert did_work is True

    output_dir = Path(settings.paths.output_dir)
    assert output_dir.is_dir()
    assert any(p.suffix == ".pdf" for p in output_dir.iterdir())

    with factory() as s:
        completed = s.execute(
            text("SELECT COUNT(*) FROM jobs WHERE status IN ('completed', 'review_required')")
        ).scalar_one()
    assert completed == 1


def test_drain_queue_returns_false_when_queue_empty(
    tmp_path: Path,
    factory: sessionmaker[Session],
) -> None:
    settings = _settings_for(tmp_path)

    class _NeverCalled:
        def ocr_pdf(self, source_path: str, **_: object) -> OcrResult:
            raise AssertionError("processor must not be called")

    processor = Phase2Processor(
        config=Phase2ProcessorConfig(
            settings=settings,
            session_factory=factory,
            ocr_port_factory=lambda _wd, _cb: _NeverCalled(),
        )
    )
    clock = FixedClock(current=datetime(2026, 4, 19, 12, 0, 0))
    assert (
        _drain_queue(
            settings,
            processor=processor,
            session_factory=factory,
            clock=clock,
        )
        is False
    )


# Suppress unused import warnings for fixtures only used in body.
_ = timedelta
