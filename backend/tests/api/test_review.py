"""Tests for the /review endpoints (Phase 4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session, sessionmaker

from docunomnom.api.deps import get_app_settings
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
    Analysis,
    ConfigSnapshot,
    DocumentPart,
    DocumentPartDecision,
    Export,
    File,
    Job,
    JobStatus,
    OcrBackend,
    ReviewItem,
    ReviewItemStatus,
    SplitProposal,
    SplitProposalSource,
    SplitProposalStatus,
)
from docunomnom.storage.db import (
    SqlAnalysisRepository,
    SqlConfigSnapshotRepository,
    SqlDocumentPartRepository,
    SqlExportRepository,
    SqlFileRepository,
    SqlJobRepository,
    SqlReviewItemRepository,
    SqlSplitProposalRepository,
)

# ------------------------------------------------------------------ helpers


def _make_pdf(path: Path, *, pages: int) -> None:
    """Write a minimal multi-page PDF to ``path``."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)


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
        ingestion=IngestionSettings(),
        worker=WorkerSettings(),
        ocr=OcrSettings(
            backend=OcrBackend.OCRMYPDF,
            languages=("eng",),
            ocrmypdf=OcrmypdfSettings(),
            external_api=ExternalOcrApiSettings(),
        ),
        network=NetworkSettings(),
        splitter=SplitterSettings(keywords=("Invoice",)),
        exporter=ExporterSettings(require_same_filesystem=False),
        ai=AiSettings(),
    )


@pytest.fixture
def patched_settings(api_client: TestClient, tmp_path: Path) -> Iterator[Settings]:
    settings = _settings_for(tmp_path)
    for d in ("input", "output", "work", "archive", "artifacts"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    api_client.app.dependency_overrides[get_app_settings] = lambda: settings
    yield settings


def _seed_review(
    session: Session,
    *,
    pdf_path: Path,
    pages: int = 5,
    job_status: JobStatus = JobStatus.REVIEW_REQUIRED,
    decision: DocumentPartDecision = DocumentPartDecision.REVIEW_REQUIRED,
    review_status: ReviewItemStatus = ReviewItemStatus.OPEN,
    with_proposals: bool = False,
) -> dict[str, int]:
    """Seed a coherent (file -> job -> analysis -> part -> review item) graph."""
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="snap-review",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    f = SqlFileRepository(session).add(
        File(
            sha256="r" * 64,
            original_name="bundle.pdf",
            size=10,
            mtime=datetime(2026, 4, 19),
            source_path=str(pdf_path),
        )
    )
    j = SqlJobRepository(session).add(
        Job(
            file_id=f.id or 0,
            status=job_status,
            mode=AiMode.OFF,
            run_key="rk-review",
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    a = SqlAnalysisRepository(session).add(
        Analysis(
            job_id=j.id or 0,
            ocr_backend=OcrBackend.OCRMYPDF,
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            page_count=pages,
            ocr_artifact_path=None,
        )
    )
    parts = list(
        SqlDocumentPartRepository(session).add_many(
            [
                DocumentPart(
                    analysis_id=a.id or 0,
                    start_page=1,
                    end_page=pages,
                    decision=decision,
                    confidence=0.5,
                )
            ]
        )
    )
    part = parts[0]
    item = SqlReviewItemRepository(session).add(
        ReviewItem(part_id=part.id or 0, status=review_status)
    )
    if with_proposals:
        SqlSplitProposalRepository(session).add_many(
            [
                SplitProposal(
                    analysis_id=a.id or 0,
                    source=SplitProposalSource.RULE,
                    start_page=1,
                    end_page=pages,
                    confidence=0.5,
                    reason_code="seed",
                    status=SplitProposalStatus.APPROVED,
                )
            ]
        )
    session.commit()
    return {
        "file_id": f.id or 0,
        "job_id": j.id or 0,
        "analysis_id": a.id or 0,
        "part_id": part.id or 0,
        "item_id": item.id or 0,
    }


def _seed_completed_with_export(session: Session, *, pdf_path: Path) -> dict[str, int]:
    """Seed a job in COMPLETED with an exported part for the reopen tests."""
    ids = _seed_review(
        session,
        pdf_path=pdf_path,
        job_status=JobStatus.COMPLETED,
        decision=DocumentPartDecision.AUTO_EXPORT,
        review_status=ReviewItemStatus.DONE,
    )
    export = SqlExportRepository(session).add(
        Export(
            part_id=ids["part_id"],
            output_path=str(pdf_path.parent / "exported.pdf"),
            output_name="exported.pdf",
            sha256="x" * 64,
        )
    )
    SqlDocumentPartRepository(session).attach_export(ids["part_id"], export.id or 0)
    session.commit()
    return ids


# ------------------------------------------------------------------ list/detail


def test_review_list_empty(api_client: TestClient, patched_settings: Settings) -> None:
    response = api_client.get("/api/v1/review")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_review_list_returns_open_items(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=5)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)

    response = api_client.get("/api/v1/review")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == ids["item_id"]
    assert body["items"][0]["status"] == "open"
    assert body["items"][0]["file_name"] == "bundle.pdf"


def test_review_list_filter_by_status(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=3)
    with session_factory() as s:
        _seed_review(s, pdf_path=pdf, review_status=ReviewItemStatus.DONE)

    response = api_client.get("/api/v1/review", params={"status": "open"})
    assert response.status_code == 200
    assert response.json()["total"] == 0

    response = api_client.get("/api/v1/review", params={"status": "done"})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_review_detail_returns_proposals_markers_and_pdf_url(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=5)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf, with_proposals=True)

    response = api_client.get(f"/api/v1/review/{ids['item_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["id"] == ids["item_id"]
    assert body["markers"] == []
    assert len(body["proposals"]) == 1
    assert body["pdf_url"].endswith(f"/review/{ids['item_id']}/pdf")


def test_review_detail_unknown_returns_404(
    api_client: TestClient,
    patched_settings: Settings,
) -> None:
    response = api_client.get("/api/v1/review/999")
    assert response.status_code == 404


# ------------------------------------------------------------------ markers


def test_put_markers_replaces_set_atomically(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=5)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)

    # Initial set with two starts.
    r1 = api_client.put(
        f"/api/v1/review/{ids['item_id']}/markers",
        json={"markers": [{"page_no": 2, "kind": "start"}, {"page_no": 4, "kind": "start"}]},
    )
    assert r1.status_code == 200
    assert {m["page_no"] for m in r1.json()} == {2, 4}

    # Replacement removes the old set entirely.
    r2 = api_client.put(
        f"/api/v1/review/{ids['item_id']}/markers",
        json={"markers": [{"page_no": 3, "kind": "start"}]},
    )
    assert r2.status_code == 200
    assert [m["page_no"] for m in r2.json()] == [3]

    # Item flips to in_progress on first marker write.
    detail = api_client.get(f"/api/v1/review/{ids['item_id']}").json()
    assert detail["item"]["status"] == "in_progress"


def test_put_markers_rejects_out_of_range(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=5)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)

    response = api_client.put(
        f"/api/v1/review/{ids['item_id']}/markers",
        json={"markers": [{"page_no": 99, "kind": "start"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_marker"


# ------------------------------------------------------------------ finalize


def test_finalize_with_no_markers_exports_single_part(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=4)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf, pages=4)

    response = api_client.post(f"/api/v1/review/{ids['item_id']}/finalize")
    assert response.status_code == 200
    body = response.json()
    assert body["derived_count"] == 1
    assert len(body["exported_part_ids"]) == 1
    assert body["job_status"] == "completed"

    output_files = list((tmp_path / "output").glob("*.pdf"))
    assert len(output_files) == 1


def test_finalize_with_markers_exports_multiple_parts(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=6)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf, pages=6)

    api_client.put(
        f"/api/v1/review/{ids['item_id']}/markers",
        json={"markers": [{"page_no": 3, "kind": "start"}, {"page_no": 5, "kind": "start"}]},
    )
    response = api_client.post(f"/api/v1/review/{ids['item_id']}/finalize")
    assert response.status_code == 200
    body = response.json()
    assert body["derived_count"] == 3
    assert len(body["exported_part_ids"]) == 3
    assert body["job_status"] == "completed"

    output_files = sorted((tmp_path / "output").glob("*.pdf"))
    assert len(output_files) == 3


def test_finalize_already_done_returns_409(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=2)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf, pages=2)

    assert api_client.post(f"/api/v1/review/{ids['item_id']}/finalize").status_code == 200
    second = api_client.post(f"/api/v1/review/{ids['item_id']}/finalize")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_done"


def test_finalize_missing_pdf_returns_409(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "ghost.pdf"
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf, pages=2)

    response = api_client.post(f"/api/v1/review/{ids['item_id']}/finalize")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pdf_missing"


# ------------------------------------------------------------------ pdf


def test_pdf_full_stream(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=2)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)

    response = api_client.get(f"/api/v1/review/{ids['item_id']}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["accept-ranges"] == "bytes"
    assert int(response.headers["content-length"]) == pdf.stat().st_size
    assert response.content == pdf.read_bytes()


def test_pdf_range_request(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=3)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)

    full = pdf.read_bytes()
    response = api_client.get(
        f"/api/v1/review/{ids['item_id']}/pdf",
        headers={"Range": "bytes=10-49"},
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 10-49/{len(full)}"
    assert response.content == full[10:50]


def test_pdf_outside_allowed_root_returns_403(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path.parent / "outside.pdf"
    _make_pdf(elsewhere, pages=1)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=elsewhere)

    response = api_client.get(f"/api/v1/review/{ids['item_id']}/pdf")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_path"


# ------------------------------------------------------------------ reopen


def test_reopen_history_creates_review_and_transitions_job(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=3)
    with session_factory() as s:
        ids = _seed_completed_with_export(s, pdf_path=pdf)

    response = api_client.post(f"/api/v1/history/{ids['part_id']}/reopen")
    assert response.status_code == 200
    body = response.json()
    assert body["part_id"] == ids["part_id"]
    assert body["job_id"] == ids["job_id"]

    listed = api_client.get("/api/v1/review", params={"status": "open"}).json()
    assert any(item["part_id"] == ids["part_id"] for item in listed["items"])

    job = api_client.get(f"/api/v1/jobs/{ids['job_id']}").json()
    assert job["status"] == "review_required"


def test_reopen_blocks_when_open_review_already_exists(
    api_client: TestClient,
    patched_settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "input" / "bundle.pdf"
    _make_pdf(pdf, pages=2)
    with session_factory() as s:
        ids = _seed_review(s, pdf_path=pdf)  # already open

    response = api_client.post(f"/api/v1/history/{ids['part_id']}/reopen")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_open"
