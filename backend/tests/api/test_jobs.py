"""Tests for the /jobs endpoints."""

from __future__ import annotations

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
    ConfigSnapshot,
    File,
    Job,
    JobStatus,
    OcrBackend,
)
from docunomnom.storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobRepository,
)


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
        exporter=ExporterSettings(),
        ai=AiSettings(),
    )


@pytest.fixture
def patched_settings(api_client: TestClient, tmp_path: Path) -> Settings:
    settings = _settings_for(tmp_path)
    api_client.app.dependency_overrides[get_app_settings] = lambda: settings
    return settings


def _seed_job(
    session: Session,
    *,
    status: JobStatus = JobStatus.PENDING,
    sha: str = "a" * 64,
) -> int:
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash=f"snap-{sha[:8]}",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    f = SqlFileRepository(session).add(
        File(
            sha256=sha,
            original_name="doc.pdf",
            size=10,
            mtime=datetime(2026, 4, 19, 12, 0, 0),
            source_path="/tmp/doc.pdf",
        )
    )
    j = SqlJobRepository(session).add(
        Job(
            file_id=f.id or 0,
            status=status,
            mode=AiMode.OFF,
            run_key=f"rk-{sha[:16]}",
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    session.commit()
    assert j.id is not None
    return j.id


def test_list_jobs_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0
    assert payload["limit"] == 50
    assert payload["offset"] == 0


def test_list_jobs_returns_summaries(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        _seed_job(s, status=JobStatus.PENDING, sha="a" * 64)
        _seed_job(s, status=JobStatus.FAILED, sha="b" * 64)

    response = api_client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["status"] for item in body["items"]} == {"pending", "failed"}


def test_list_jobs_filter_by_status(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        _seed_job(s, status=JobStatus.PENDING, sha="a" * 64)
        _seed_job(s, status=JobStatus.FAILED, sha="b" * 64)

    response = api_client.get("/api/v1/jobs", params={"status": "failed"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


def test_list_jobs_invalid_status(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/jobs", params={"status": "bogus"})
    assert response.status_code == 422


def test_get_job_not_found(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/jobs/9999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_get_job_returns_detail(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        job_id = _seed_job(s)

    response = api_client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "pending"
    assert "events" in body


def test_retry_only_failed_jobs(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        pending_id = _seed_job(s, status=JobStatus.PENDING, sha="a" * 64)
        failed_id = _seed_job(s, status=JobStatus.FAILED, sha="b" * 64)

    bad = api_client.post(f"/api/v1/jobs/{pending_id}/retry")
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "invalid_state"

    ok = api_client.post(f"/api/v1/jobs/{failed_id}/retry")
    assert ok.status_code == 200
    assert ok.json()["status"] == "pending"


def test_retry_unknown_job(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/jobs/9999/retry")
    assert response.status_code == 404


def test_reprocess_creates_new_job(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    patched_settings: Settings,
) -> None:
    with session_factory() as s:
        job_id = _seed_job(s, status=JobStatus.COMPLETED, sha="c" * 64)

    response = api_client.post(f"/api/v1/jobs/{job_id}/reprocess")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] != job_id
    assert body["status"] == "pending"

    listing = api_client.get("/api/v1/jobs").json()
    assert listing["total"] == 2


def test_rescan_runs_synchronously(
    api_client: TestClient,
    patched_settings: Settings,
) -> None:
    inp = Path(patched_settings.paths.input_dir)
    inp.mkdir(parents=True, exist_ok=True)
    pdf_path = inp / "incoming.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    response = api_client.post("/api/v1/jobs/rescan")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enqueued"] == 1


def test_rescan_returns_zero_when_input_dir_missing(
    api_client: TestClient,
    patched_settings: Settings,
) -> None:
    # Do not create the input dir.
    response = api_client.post("/api/v1/jobs/rescan")
    assert response.status_code == 200
    assert response.json() == {"enqueued": 0}
