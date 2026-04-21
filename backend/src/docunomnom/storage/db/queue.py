"""Database-backed job queue (single-writer / SQLite).

Implements ``JobQueuePort``. Lease acquisition follows the SQL skeleton in
plan §8: select one available job (pending OR processing-with-expired-lease)
and atomically transition it to processing with a fresh lease.

The repository operates inside the caller's transaction. The Phase 1 worker
runs each lease/heartbeat as a short transaction so SQLite write contention
stays low.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.models import Job, JobStatus
from ...core.ports.clock import ClockPort
from ...core.usecases.transition_job import ensure_transition_allowed
from .models import JobORM
from .repositories import _to_job


class SqlJobQueue:
    """``JobQueuePort`` implementation using SQLAlchemy."""

    def __init__(self, session: Session, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    def lease_one(
        self,
        *,
        lease_ttl: timedelta,
        max_attempts: int,
    ) -> Job | None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        now = self._clock.now()
        # Pick the oldest available job: either pending, or processing whose
        # lease has expired (crash recovery). The single-worker invariant
        # makes a plain SELECT safe; on PostgreSQL we will switch to
        # ``FOR UPDATE SKIP LOCKED`` here.
        stmt = (
            select(JobORM)
            .where(
                or_(
                    JobORM.status == JobStatus.PENDING.value,
                    (JobORM.status == JobStatus.PROCESSING.value)
                    & (JobORM.lease_until.is_(None) | (JobORM.lease_until <= now)),
                )
            )
            .order_by(JobORM.created_at.asc(), JobORM.id.asc())
            .limit(1)
        )
        row = self._session.scalars(stmt).first()

        if row is None:
            return None

        next_attempt = row.attempt + 1
        if next_attempt > max_attempts:
            # Max attempts exhausted: move to terminal failed state and skip
            # leasing this round.
            ensure_transition_allowed(JobStatus(row.status), JobStatus.FAILED)
            row.status = JobStatus.FAILED.value
            row.error_code = row.error_code or "max_attempts_exhausted"
            row.error_msg = row.error_msg or (f"job exceeded max_attempts={max_attempts}")
            row.lease_until = None
            self._session.flush()
            return None

        # Validate the transition (only meaningful when picking up a pending
        # job; an expired-lease pickup stays in processing).
        if row.status == JobStatus.PENDING.value:
            ensure_transition_allowed(JobStatus.PENDING, JobStatus.PROCESSING)
        row.status = JobStatus.PROCESSING.value
        row.attempt = next_attempt
        row.lease_until = now + lease_ttl
        self._session.flush()
        return _to_job(row)

    def heartbeat(self, job_id: int, *, lease_ttl: timedelta) -> bool:
        row = self._session.get(JobORM, job_id)
        if row is None:
            return False
        if row.status != JobStatus.PROCESSING.value:
            return False
        now = self._clock.now()
        if row.lease_until is not None and row.lease_until <= now:
            # Lease already expired; some other actor may have re-leased it.
            return False
        row.lease_until = now + lease_ttl
        self._session.flush()
        return True
