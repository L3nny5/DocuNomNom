"""Repository smoke tests against an in-memory SQLite engine."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from docunomnom.core.models import (
    AiBackend,
    AiMode,
    ConfigSnapshot,
    File,
    Job,
    JobEvent,
    JobStatus,
    OcrBackend,
)
from docunomnom.core.usecases.transition_job import IllegalJobTransitionError
from docunomnom.storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobRepository,
)


def _make_snapshot(session: Session, *, hash_: str = "snap-hash-1") -> ConfigSnapshot:
    snapshots = SqlConfigSnapshotRepository(session)
    return snapshots.get_or_create(
        ConfigSnapshot(
            hash=hash_,
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={"x": 1},
        )
    )


def _make_file(session: Session, *, sha256: str = "f" * 64) -> File:
    files = SqlFileRepository(session)
    return files.add(
        File(
            sha256=sha256,
            original_name="doc.pdf",
            size=1234,
            mtime=datetime(2026, 4, 19, 10, 0),
            source_path="/in/doc.pdf",
        )
    )


def test_file_repo_roundtrip(session: Session) -> None:
    files = SqlFileRepository(session)
    f = _make_file(session)
    assert f.id is not None
    again = files.get(f.id)
    assert again is not None
    assert again.sha256 == f.sha256
    assert again.original_name == "doc.pdf"
    assert files.find_by_sha256(f.sha256) == [again]


def test_config_snapshot_get_or_create_is_idempotent(session: Session) -> None:
    a = _make_snapshot(session, hash_="dup")
    b = _make_snapshot(session, hash_="dup")
    assert a.id == b.id


def test_job_repo_creates_with_pending_status(session: Session) -> None:
    snap = _make_snapshot(session)
    file = _make_file(session)
    jobs = SqlJobRepository(session)
    job = jobs.add(
        Job(
            file_id=file.id or 0,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key="r" * 64,
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    assert job.id is not None
    fetched = jobs.get(job.id)
    assert fetched is not None
    assert fetched.status is JobStatus.PENDING


def test_has_active_with_run_key(session: Session) -> None:
    snap = _make_snapshot(session)
    file = _make_file(session)
    jobs = SqlJobRepository(session)
    rk = "active-key-1"
    assert jobs.has_active_with_run_key(rk) is False

    jobs.add(
        Job(
            file_id=file.id or 0,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key=rk,
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    assert jobs.has_active_with_run_key(rk) is True

    # Same run_key in terminal state must not count as active.
    file2 = _make_file(session, sha256="g" * 64)
    snap2 = _make_snapshot(session, hash_="other-snap")
    jobs.add(
        Job(
            file_id=file2.id or 0,
            status=JobStatus.COMPLETED,
            mode=AiMode.OFF,
            run_key="terminal-key",
            config_snapshot_id=snap2.id or 0,
            pipeline_version="1.0.0",
        )
    )
    assert jobs.has_active_with_run_key("terminal-key") is False


def test_transition_uses_state_machine(session: Session) -> None:
    snap = _make_snapshot(session)
    file = _make_file(session)
    jobs = SqlJobRepository(session)
    job = jobs.add(
        Job(
            file_id=file.id or 0,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key="x" * 64,
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    assert job.id is not None
    jobs.transition(job.id, new_status=JobStatus.PROCESSING)
    after = jobs.get(job.id)
    assert after is not None
    assert after.status is JobStatus.PROCESSING

    with pytest.raises(IllegalJobTransitionError):
        jobs.transition(job.id, new_status=JobStatus.PENDING)


def test_job_event_append(session: Session) -> None:
    snap = _make_snapshot(session)
    file = _make_file(session)
    jobs = SqlJobRepository(session)
    events = SqlJobEventRepository(session)
    job = jobs.add(
        Job(
            file_id=file.id or 0,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key="ev" * 32,
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    assert job.id is not None
    event = events.append(JobEvent(job_id=job.id, type="enqueued", payload={"why": "test"}))
    assert event.id is not None
    assert event.type == "enqueued"
    assert event.payload == {"why": "test"}
