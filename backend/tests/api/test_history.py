"""Tests for the /history endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

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
)
from docunomnom.storage.db import (
    SqlAnalysisRepository,
    SqlConfigSnapshotRepository,
    SqlDocumentPartRepository,
    SqlExportRepository,
    SqlFileRepository,
    SqlJobRepository,
)


def _seed_history(session: Session) -> int:
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="h-snap",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    f = SqlFileRepository(session).add(
        File(
            sha256="d" * 64,
            original_name="invoice.pdf",
            size=1234,
            mtime=datetime(2026, 4, 19),
            source_path="/tmp/invoice.pdf",
        )
    )
    j = SqlJobRepository(session).add(
        Job(
            file_id=f.id or 0,
            status=JobStatus.COMPLETED,
            mode=AiMode.OFF,
            run_key="rk-history",
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
            page_count=1,
        )
    )
    parts = list(
        SqlDocumentPartRepository(session).add_many(
            [
                DocumentPart(
                    analysis_id=a.id or 0,
                    start_page=1,
                    end_page=1,
                    decision=DocumentPartDecision.AUTO_EXPORT,
                    confidence=0.9,
                )
            ]
        )
    )
    part = parts[0]
    assert part.id is not None
    export = SqlExportRepository(session).add(
        Export(
            part_id=part.id,
            output_path="/data/output/invoice_part_001.pdf",
            output_name="invoice_part_001.pdf",
            sha256="e" * 64,
        )
    )
    assert export.id is not None
    SqlDocumentPartRepository(session).attach_export(part.id, export.id)
    session.commit()
    return part.id


def test_history_list_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_history_list_returns_exported_parts(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        _seed_history(s)

    response = api_client.get("/api/v1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["file_name"] == "invoice.pdf"
    assert item["output_name"] == "invoice_part_001.pdf"


def test_history_get_one(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        part_id = _seed_history(s)

    response = api_client.get(f"/api/v1/history/{part_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["part_id"] == part_id
    assert body["file_name"] == "invoice.pdf"


def test_history_get_unknown_returns_404(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/history/9999")
    assert response.status_code == 404
