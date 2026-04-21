"""Database-backed job loop.

Implements the Phase 1 worker contract:

- lease the next available job (``pending`` OR ``processing`` whose lease
  expired ⇒ crash recovery),
- send periodic heartbeats during processing,
- transition to ``completed`` / ``review_required`` / ``failed`` via the
  state machine,
- terminal ``failed`` transition once ``max_attempts`` is exhausted (also
  enforced by the queue itself when leasing).

The OCR / AI / exporter pipeline is *not* part of Phase 1. Real processing
is delegated to a ``JobProcessor`` callable that is injected at construction
time. Tests provide simple processors; production wiring will land in later
phases together with the actual pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from ..core.events import JobEventType
from ..core.models import Job, JobStatus
from ..core.ports.clock import ClockPort
from ..core.ports.job_queue import JobQueuePort
from ..core.ports.storage import JobEventRepositoryPort, JobRepositoryPort

logger = logging.getLogger(__name__)


class JobProcessingError(RuntimeError):
    """Raised by a processor to signal a recoverable processing failure.

    The job is transitioned back to ``failed`` (terminal) with the supplied
    error code/message; the queue will not re-lease automatically — operator
    or API action is required to ``retry``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Outcome returned by a processor."""

    status: JobStatus  # COMPLETED or REVIEW_REQUIRED


class JobProcessor(Protocol):
    def __call__(self, job: Job, *, heartbeat: Callable[[], bool]) -> JobOutcome:
        """Process ``job`` and return its terminal outcome.

        Implementations must call ``heartbeat()`` periodically for any
        long-running step. ``heartbeat`` returns False when our lease is
        gone, in which case the processor should stop early.
        """
        ...


@dataclass(slots=True)
class JobLoopConfig:
    poll_interval: timedelta = timedelta(seconds=2)
    lease_ttl: timedelta = timedelta(seconds=120)
    heartbeat_interval: timedelta = timedelta(seconds=30)
    max_attempts: int = 3


class JobLoop:
    """Single-worker job loop. Designed for one process / one thread.

    ``run_forever`` blocks until ``stop`` is called. ``run_once`` does a
    single iteration and is the primary entry point for tests.
    """

    def __init__(
        self,
        *,
        queue: JobQueuePort,
        jobs: JobRepositoryPort,
        events: JobEventRepositoryPort,
        clock: ClockPort,
        processor: JobProcessor,
        config: JobLoopConfig | None = None,
    ) -> None:
        self._queue = queue
        self._jobs = jobs
        self._events = events
        self._clock = clock
        self._processor = processor
        self._config = config or JobLoopConfig()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            did_work = self.run_once()
            if not did_work:
                # Sleep in small slices so stop() is responsive.
                self._sleep_responsive(self._config.poll_interval.total_seconds())

    def run_once(self) -> bool:
        """Lease and process at most one job. Returns True iff one was processed."""
        job = self._queue.lease_one(
            lease_ttl=self._config.lease_ttl,
            max_attempts=self._config.max_attempts,
        )
        if job is None:
            return False
        if job.id is None:
            raise RuntimeError("leased job has no id")
        self._record(job.id, JobEventType.LEASED.value, {"attempt": job.attempt})

        heartbeat = _make_heartbeat(
            queue=self._queue,
            clock=self._clock,
            events=self._events,
            job_id=job.id,
            interval=self._config.heartbeat_interval,
            ttl=self._config.lease_ttl,
        )

        try:
            outcome = self._processor(job, heartbeat=heartbeat)
        except JobProcessingError as exc:
            logger.warning("job %s failed: %s", job.id, exc.code)
            self._jobs.transition(
                job.id,
                new_status=JobStatus.FAILED,
                error_code=exc.code,
                error_msg=exc.message,
            )
            self._record(
                job.id,
                JobEventType.FAILED.value,
                {"code": exc.code, "message": exc.message},
            )
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("job %s crashed in processor", job.id)
            self._jobs.transition(
                job.id,
                new_status=JobStatus.FAILED,
                error_code="processor_exception",
                error_msg=str(exc),
            )
            self._record(
                job.id,
                JobEventType.FAILED.value,
                {"code": "processor_exception", "message": str(exc)},
            )
            return True

        if outcome.status not in (JobStatus.COMPLETED, JobStatus.REVIEW_REQUIRED):
            raise ValueError(f"processor returned invalid outcome status: {outcome.status!r}")
        self._jobs.transition(job.id, new_status=outcome.status)
        self._record(job.id, outcome.status.value, {})
        return True

    def _record(self, job_id: int, type_: str, payload: dict[str, object]) -> None:
        from ..core.models import JobEvent

        self._events.append(JobEvent(job_id=job_id, type=type_, payload=payload))

    def _sleep_responsive(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))


def _make_heartbeat(
    *,
    queue: JobQueuePort,
    clock: ClockPort,
    events: JobEventRepositoryPort,
    job_id: int,
    interval: timedelta,
    ttl: timedelta,
) -> Callable[[], bool]:
    """Build a heartbeat callable that throttles to ``interval``."""
    state = {"last_at": clock.now() - interval - timedelta(seconds=1)}

    def heartbeat() -> bool:
        from ..core.models import JobEvent

        now = clock.now()
        if (now - state["last_at"]) < interval:
            return True
        ok = queue.heartbeat(job_id, lease_ttl=ttl)
        state["last_at"] = now
        events.append(
            JobEvent(job_id=job_id, type=JobEventType.HEARTBEAT.value, payload={"ok": ok})
        )
        return ok

    return heartbeat
