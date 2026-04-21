"""Worker process entry point.

Wires the watcher and the job-drain loop with the Phase 2 pipeline:

1. Apply database migrations.
2. Build the SQLAlchemy engine and session factory.
3. Construct the OCR adapter factory and the Phase2Processor.
4. Run a polling loop that alternates a watcher scan with one ``_drain_queue``
   call, sleeping briefly when there is nothing to do.

``_drain_queue`` (Phase 3 refactor) splits each job into three short
transactions — lease, processor work (which manages its own session),
finalize — so on a real file-backed SQLite database the processor's
own write transaction never contends with an outer write lock held by
the loop. ``JobLoop`` itself is still kept for the in-memory unit tests
that exercise the loop semantics in isolation.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import FrameType

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ..adapters.clock import SystemClock
from ..config import Settings, get_settings
from ..core.events import JobEventType
from ..core.models import JobEvent, JobStatus
from ..core.ports.clock import ClockPort
from ..runtime import (
    LogEvent,
    PreflightError,
    SingleWorkerLockError,
    acquire_single_worker_lock,
    configure_logging,
    run_preflight,
)
from ..storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobQueue,
    SqlJobRepository,
    create_engine,
    make_session_factory,
    run_alembic_upgrade,
)
from .ai_factory import build_ai_split_port_factory
from .loop import JobLoopConfig, JobProcessingError, JobProcessor
from .ocr_factory import build_ocr_port_factory
from .processor import Phase2Processor, Phase2ProcessorConfig
from .watcher import StabilityWatcher, settings_to_config_snapshot

logger = logging.getLogger("docunomnom.worker")


def _make_loop_config(settings: Settings) -> JobLoopConfig:
    return JobLoopConfig(
        poll_interval=timedelta(seconds=settings.worker.poll_interval_seconds),
        lease_ttl=timedelta(seconds=settings.worker.lease_ttl_seconds),
        heartbeat_interval=timedelta(seconds=settings.worker.heartbeat_interval_seconds),
        max_attempts=settings.worker.max_attempts,
    )


def _scan_input_dir(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session],
    clock: ClockPort,
) -> int:
    """Run one watcher pass in its own short transaction."""
    with session_factory() as session:
        watcher = StabilityWatcher(
            input_dir=Path(settings.paths.input_dir),
            ingestion=settings.ingestion,
            pipeline_version=settings.runtime.pipeline_version,
            clock=clock,
            files=SqlFileRepository(session),
            jobs=SqlJobRepository(session),
            events=SqlJobEventRepository(session),
            snapshots=SqlConfigSnapshotRepository(session),
            snapshot_factory=lambda: settings_to_config_snapshot(settings),
        )
        result = watcher.scan_once()
        session.commit()
        return len(result.enqueued_jobs)


def _drain_queue(
    settings: Settings,
    *,
    processor: JobProcessor,
    session_factory: sessionmaker[Session],
    clock: ClockPort,
) -> bool:
    """Process up to one queued job using three short transactions.

    Why three transactions instead of one big outer session: the
    processor opens its OWN session via ``session_factory`` to write the
    analysis. On a real file-backed SQLite database, holding a
    write-touching outer session open across the processor invocation
    would block the processor's own write transaction. Splitting the
    drain into ``lease`` -> ``processor`` -> ``finalize`` keeps every
    write transaction short and avoids that contention.
    """
    cfg = _make_loop_config(settings)

    # 1) Lease in a short transaction and commit before yielding.
    with session_factory() as lease_session:
        queue = SqlJobQueue(lease_session, clock)
        events = SqlJobEventRepository(lease_session)
        leased = queue.lease_one(lease_ttl=cfg.lease_ttl, max_attempts=cfg.max_attempts)
        if leased is None:
            lease_session.commit()
            return False
        if leased.id is None:
            raise RuntimeError("leased job has no id")
        events.append(
            JobEvent(
                job_id=leased.id,
                type=JobEventType.LEASED.value,
                payload={"attempt": leased.attempt},
            )
        )
        lease_session.commit()

    job_id = leased.id

    # 2) Build a short-transaction heartbeat and run the processor.
    heartbeat = _short_txn_heartbeat(
        session_factory=session_factory,
        clock=clock,
        job_id=job_id,
        cfg=cfg,
    )

    try:
        outcome = processor(leased, heartbeat=heartbeat)
    except JobProcessingError as exc:
        logger.warning("job %s failed: %s", job_id, exc.code)
        with session_factory() as fail_session:
            SqlJobRepository(fail_session).transition(
                job_id,
                new_status=JobStatus.FAILED,
                error_code=exc.code,
                error_msg=exc.message,
            )
            SqlJobEventRepository(fail_session).append(
                JobEvent(
                    job_id=job_id,
                    type=JobEventType.FAILED.value,
                    payload={"code": exc.code, "message": exc.message},
                )
            )
            fail_session.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("job %s crashed in processor", job_id)
        with session_factory() as crash_session:
            SqlJobRepository(crash_session).transition(
                job_id,
                new_status=JobStatus.FAILED,
                error_code="processor_exception",
                error_msg=str(exc),
            )
            SqlJobEventRepository(crash_session).append(
                JobEvent(
                    job_id=job_id,
                    type=JobEventType.FAILED.value,
                    payload={"code": "processor_exception", "message": str(exc)},
                )
            )
            crash_session.commit()
        return True

    if outcome.status not in (JobStatus.COMPLETED, JobStatus.REVIEW_REQUIRED):
        raise ValueError(f"processor returned invalid outcome status: {outcome.status!r}")

    # 3) Finalize transition + event in a short transaction.
    with session_factory() as final_session:
        SqlJobRepository(final_session).transition(job_id, new_status=outcome.status)
        SqlJobEventRepository(final_session).append(
            JobEvent(job_id=job_id, type=outcome.status.value, payload={})
        )
        final_session.commit()
    return True


def _short_txn_heartbeat(
    *,
    session_factory: sessionmaker[Session],
    clock: ClockPort,
    job_id: int,
    cfg: JobLoopConfig,
) -> Callable[[], bool]:
    """Build a heartbeat that opens its own short session per call.

    Throttles to ``cfg.heartbeat_interval`` like the in-loop variant; the
    closure persists across processor invocations so the throttle works.

    The processor's session may hold a SQLite write lock for the duration
    of one job (OCR + analysis writes are all in one transaction). The
    heartbeat is advisory — if it cannot acquire the write lock within
    the configured ``busy_timeout`` we swallow the resulting
    ``OperationalError``, leave ``last_at`` untouched, and report success
    so processing continues; the next ``heartbeat()`` call will retry
    once the processor's transaction has committed.
    """
    last_at = clock.now() - cfg.heartbeat_interval - timedelta(seconds=1)

    def heartbeat() -> bool:
        nonlocal last_at
        now = clock.now()
        if (now - last_at) < cfg.heartbeat_interval:
            return True
        try:
            with session_factory() as hb_session:
                queue = SqlJobQueue(hb_session, clock)
                events = SqlJobEventRepository(hb_session)
                ok = queue.heartbeat(job_id, lease_ttl=cfg.lease_ttl)
                events.append(
                    JobEvent(
                        job_id=job_id,
                        type=JobEventType.HEARTBEAT.value,
                        payload={"ok": ok},
                    )
                )
                hb_session.commit()
                last_at = now
                return ok
        except OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.debug("heartbeat skipped: database busy")
                return True
            raise

    return heartbeat


def main() -> None:
    """Run the worker process until SIGTERM or SIGINT is received.

    Phase 6 hardened startup sequence:

    1. Configure logging from settings.
    2. Run :func:`run_preflight` (paths, sqlite mount, AI coherence,
       splitter weights). Refuse to start when any check fails.
    3. Acquire the single-worker advisory PID-file lock under
       ``work_dir``. Refuse to start when another live worker owns it.
    4. Apply database migrations.
    5. Enter the polling loop.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "%s ocr_backend=%s ai_backend=%s ai_mode=%s pipeline_version=%s",
        LogEvent.WORKER_STARTING,
        settings.ocr.backend.value,
        settings.ai.backend.value,
        settings.ai.mode.value,
        settings.runtime.pipeline_version,
    )

    try:
        run_preflight(settings)
    except PreflightError as exc:
        logger.error("%s code=%s detail=%s", LogEvent.WORKER_PREFLIGHT_FAIL, exc.code, exc.message)
        raise SystemExit(2) from exc
    logger.info("%s", LogEvent.WORKER_PREFLIGHT_OK)

    try:
        worker_lock = acquire_single_worker_lock(Path(settings.paths.work_dir))
    except SingleWorkerLockError as exc:
        logger.error("%s detail=%s", LogEvent.WORKER_LOCK_DENIED, exc)
        raise SystemExit(3) from exc
    logger.info("%s path=%s pid=%s", LogEvent.WORKER_LOCK_ACQUIRED, worker_lock.path, _os_pid())

    try:
        try:
            run_alembic_upgrade(settings.storage.database_url)
            logger.info("%s", LogEvent.DB_MIGRATION_OK)
        except Exception:
            logger.exception("%s", LogEvent.DB_MIGRATION_FAIL)
            raise

        engine = create_engine(settings.storage.database_url)
        session_factory = make_session_factory(engine)
        clock: ClockPort = SystemClock()

        processor = Phase2Processor(
            config=Phase2ProcessorConfig(
                settings=settings,
                session_factory=session_factory,
                ocr_port_factory=build_ocr_port_factory(settings),
                ai_split_port_factory=build_ai_split_port_factory(settings),
            )
        )

        stop_event = threading.Event()

        def _shutdown(signum: int, _frame: FrameType | None) -> None:
            logger.info("%s signal=%s", LogEvent.WORKER_STOPPING, signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        poll_seconds = max(
            0.1,
            min(
                settings.worker.poll_interval_seconds,
                settings.ingestion.poll_interval_seconds,
            ),
        )
        last_scan = 0.0

        logger.info("%s", LogEvent.WORKER_READY)
        try:
            while not stop_event.is_set():
                now = time.monotonic()
                if (now - last_scan) >= settings.ingestion.poll_interval_seconds:
                    try:
                        _scan_input_dir(
                            settings,
                            session_factory=session_factory,
                            clock=clock,
                        )
                    except Exception:
                        logger.exception("%s", LogEvent.WORKER_SCAN_FAILED)
                    last_scan = now

                try:
                    did_work = _drain_queue(
                        settings,
                        processor=processor,
                        session_factory=session_factory,
                        clock=clock,
                    )
                except Exception:
                    logger.exception("%s", LogEvent.WORKER_DRAIN_FAILED)
                    did_work = False

                if not did_work:
                    stop_event.wait(timeout=poll_seconds)
        finally:
            engine.dispose()
    finally:
        worker_lock.release()


def _os_pid() -> int:
    import os

    return os.getpid()


if __name__ == "__main__":
    main()
