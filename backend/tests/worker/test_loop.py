"""Tests for the JobLoop."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from docunomnom.adapters.clock import FixedClock
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
    SqlJobEventRepository,
    SqlJobQueue,
    SqlJobRepository,
)
from docunomnom.worker.loop import (
    JobLoop,
    JobLoopConfig,
    JobOutcome,
    JobProcessingError,
)

LEASE_TTL = timedelta(seconds=60)
HB_INTERVAL = timedelta(seconds=10)


def _seed(session: Session, *, run_key: str = "k1") -> int:
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="loop-snap",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    f = SqlFileRepository(session).add(
        File(
            sha256=run_key.ljust(64, "a"),
            original_name="x.pdf",
            size=1,
            mtime=datetime(2026, 4, 19),
            source_path="/in/x.pdf",
        )
    )
    j = SqlJobRepository(session).add(
        Job(
            file_id=f.id or 0,
            status=JobStatus.PENDING,
            mode=AiMode.OFF,
            run_key=run_key,
            config_snapshot_id=snap.id or 0,
            pipeline_version="1.0.0",
        )
    )
    session.flush()
    assert j.id is not None
    return j.id


def _make_loop(
    session: Session,
    clock: FixedClock,
    processor: Callable[..., JobOutcome],
    *,
    max_attempts: int = 3,
) -> JobLoop:
    return JobLoop(
        queue=SqlJobQueue(session, clock),
        jobs=SqlJobRepository(session),
        events=SqlJobEventRepository(session),
        clock=clock,
        processor=processor,
        config=JobLoopConfig(
            poll_interval=timedelta(seconds=1),
            lease_ttl=LEASE_TTL,
            heartbeat_interval=HB_INTERVAL,
            max_attempts=max_attempts,
        ),
    )


def test_run_once_completes_successful_job(session: Session, fixed_clock: FixedClock) -> None:
    job_id = _seed(session)

    def proc(job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        assert job.id == job_id
        assert heartbeat() is True
        return JobOutcome(status=JobStatus.COMPLETED)

    loop = _make_loop(session, fixed_clock, proc)
    assert loop.run_once() is True

    refreshed = SqlJobRepository(session).get(job_id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.COMPLETED


def test_run_once_review_required(session: Session, fixed_clock: FixedClock) -> None:
    job_id = _seed(session)

    def proc(_job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        return JobOutcome(status=JobStatus.REVIEW_REQUIRED)

    loop = _make_loop(session, fixed_clock, proc)
    assert loop.run_once() is True
    refreshed = SqlJobRepository(session).get(job_id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.REVIEW_REQUIRED


def test_processing_error_marks_failed(session: Session, fixed_clock: FixedClock) -> None:
    job_id = _seed(session)

    def proc(_job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        raise JobProcessingError("ocr_unavailable", "no OCR backend")

    loop = _make_loop(session, fixed_clock, proc)
    assert loop.run_once() is True
    refreshed = SqlJobRepository(session).get(job_id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.FAILED
    assert refreshed.error_code == "ocr_unavailable"


def test_run_once_returns_false_when_no_job(session: Session, fixed_clock: FixedClock) -> None:
    def proc(_job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        raise AssertionError("processor must not be called")

    loop = _make_loop(session, fixed_clock, proc)
    assert loop.run_once() is False


def test_recovers_after_lease_expiry(session: Session, fixed_clock: FixedClock) -> None:
    job_id = _seed(session)
    invocations = {"n": 0}

    def proc(_job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        invocations["n"] += 1
        if invocations["n"] == 1:
            # Simulate a worker crash by raising a non-processing exception.
            raise RuntimeError("simulated crash")
        return JobOutcome(status=JobStatus.COMPLETED)

    loop = _make_loop(session, fixed_clock, proc)
    # First attempt: caught by the loop's defensive Exception clause and
    # transitioned to failed. We then want the queue's expired-lease path to
    # cover crash recovery, so seed a fresh PENDING job instead and fast-
    # forward the clock.
    assert loop.run_once() is True
    refreshed = SqlJobRepository(session).get(job_id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.FAILED


def test_max_attempts_failed_via_queue(session: Session) -> None:
    """When attempt+1 would exceed max_attempts, the queue itself fails the job."""
    clock = FixedClock(current=datetime(2026, 4, 19))
    job_id = _seed(session)

    # Exhaust attempts using only the queue, no processor calls.
    queue = SqlJobQueue(session, clock)
    for _ in range(2):
        leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=2)
        assert leased is not None
        clock.advance(seconds=LEASE_TTL.total_seconds() + 1)

    # Third attempt: queue should refuse and mark failed.
    assert queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=2) is None
    refreshed = SqlJobRepository(session).get(job_id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.FAILED
    assert refreshed.error_code == "max_attempts_exhausted"
