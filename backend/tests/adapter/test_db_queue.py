"""Tests for the database-backed job queue (lease / heartbeat / recovery)."""

from __future__ import annotations

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
    SqlJobQueue,
    SqlJobRepository,
)

LEASE_TTL = timedelta(seconds=60)


def _seed_pending(session: Session, *, count: int = 1) -> list[Job]:
    snap = SqlConfigSnapshotRepository(session).get_or_create(
        ConfigSnapshot(
            hash="seed-hash",
            ai_backend=AiBackend.NONE,
            ai_mode=AiMode.OFF,
            ocr_backend=OcrBackend.OCRMYPDF,
            pipeline_version="1.0.0",
            payload={},
        )
    )
    files = SqlFileRepository(session)
    jobs = SqlJobRepository(session)
    out: list[Job] = []
    for i in range(count):
        f = files.add(
            File(
                sha256=str(i).rjust(64, "0"),
                original_name=f"f{i}.pdf",
                size=10,
                mtime=datetime(2026, 4, 19),
                source_path=f"/in/f{i}.pdf",
            )
        )
        j = jobs.add(
            Job(
                file_id=f.id or 0,
                status=JobStatus.PENDING,
                mode=AiMode.OFF,
                run_key=f"rk-{i}",
                config_snapshot_id=snap.id or 0,
                pipeline_version="1.0.0",
            )
        )
        out.append(j)
    session.flush()
    return out


def test_lease_one_picks_pending(session: Session, fixed_clock: FixedClock) -> None:
    [seed] = _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert leased is not None
    assert leased.id == seed.id
    assert leased.status is JobStatus.PROCESSING
    assert leased.attempt == 1
    assert leased.lease_until == fixed_clock.now() + LEASE_TTL


def test_lease_one_returns_none_when_empty(session: Session, fixed_clock: FixedClock) -> None:
    queue = SqlJobQueue(session, fixed_clock)
    assert queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3) is None


def test_lease_skips_processing_with_active_lease(
    session: Session, fixed_clock: FixedClock
) -> None:
    [seed] = _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert leased is not None and leased.id == seed.id

    # No new job appears until the lease expires (and there is no other
    # pending job to grab).
    assert queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3) is None


def test_expired_lease_is_recovered(session: Session, fixed_clock: FixedClock) -> None:
    _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    first = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert first is not None and first.attempt == 1

    fixed_clock.advance(seconds=LEASE_TTL.total_seconds() + 1)

    second = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert second is not None
    assert second.id == first.id
    assert second.attempt == 2
    assert second.status is JobStatus.PROCESSING


def test_max_attempts_terminates_to_failed(session: Session, fixed_clock: FixedClock) -> None:
    _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    jobs = SqlJobRepository(session)

    for _ in range(3):
        leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
        assert leased is not None
        fixed_clock.advance(seconds=LEASE_TTL.total_seconds() + 1)

    extra = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert extra is None
    persisted = jobs.get(_seed_unique_id := 1)
    assert persisted is not None
    assert persisted.status is JobStatus.FAILED
    assert persisted.error_code == "max_attempts_exhausted"


def test_heartbeat_extends_lease(session: Session, fixed_clock: FixedClock) -> None:
    _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert leased is not None and leased.id is not None
    fixed_clock.advance(seconds=10)
    assert queue.heartbeat(leased.id, lease_ttl=LEASE_TTL) is True

    jobs = SqlJobRepository(session)
    refreshed = jobs.get(leased.id)
    assert refreshed is not None
    assert refreshed.lease_until == fixed_clock.now() + LEASE_TTL


def test_heartbeat_after_expiry_returns_false(session: Session, fixed_clock: FixedClock) -> None:
    _seed_pending(session)
    queue = SqlJobQueue(session, fixed_clock)
    leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert leased is not None and leased.id is not None
    fixed_clock.advance(seconds=LEASE_TTL.total_seconds() + 5)
    assert queue.heartbeat(leased.id, lease_ttl=LEASE_TTL) is False


def test_lease_picks_oldest_first(session: Session, fixed_clock: FixedClock) -> None:
    seeds = _seed_pending(session, count=3)
    queue = SqlJobQueue(session, fixed_clock)
    leased = queue.lease_one(lease_ttl=LEASE_TTL, max_attempts=3)
    assert leased is not None
    assert leased.id == seeds[0].id
