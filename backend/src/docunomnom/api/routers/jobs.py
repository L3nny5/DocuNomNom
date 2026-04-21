"""/jobs endpoints.

Listing, retrieval, retry, reprocess, and an on-demand rescan helper that
runs one watcher pass synchronously. The endpoints are intentionally
small: every state change goes through the existing job state machine
via ``SqlJobRepository.transition``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, sessionmaker

from ...config import Settings
from ...core.events import JobEventType
from ...core.models import (
    AiBackend,
    AiMode,
    ConfigSnapshot,
    Job,
    JobEvent,
    JobStatus,
    OcrBackend,
)
from ...core.ports.clock import ClockPort
from ...core.run_key import compute_config_snapshot_hash, compute_run_key
from ...storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobRepository,
)
from ...worker.watcher import StabilityWatcher, settings_to_config_snapshot
from ..deps import (
    get_app_settings,
    get_clock,
    get_session,
    get_session_factory,
)
from ..schemas.jobs import (
    JobDetailOut,
    JobEventOut,
    JobListResponse,
    JobSummaryOut,
    RescanResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

logger = logging.getLogger(__name__)


@router.get("", response_model=JobListResponse)
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> JobListResponse:
    summaries, total = SqlJobRepository(session).list_summaries(
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobSummaryOut.model_validate(s) for s in summaries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobDetailOut:
    summary = SqlJobRepository(session).get_summary(job_id)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Job not found"},
        )

    from sqlalchemy import select

    from ...storage.db.models import JobEventORM

    rows = session.scalars(
        select(JobEventORM)
        .where(JobEventORM.job_id == job_id)
        .order_by(JobEventORM.ts.asc(), JobEventORM.id.asc())
    ).all()

    events = [
        JobEventOut(
            id=int(r.id),
            job_id=r.job_id,
            type=r.type,
            ts=r.ts,
            payload=dict(r.payload),
        )
        for r in rows
    ]
    return JobDetailOut.model_validate(
        {
            **{f: getattr(summary, f) for f in summary.__slots__},
            "events": events,
        }
    )


@router.post(
    "/rescan",
    response_model=RescanResponse,
    status_code=status.HTTP_200_OK,
)
def rescan(
    settings: Settings = Depends(get_app_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory),
    clock: ClockPort = Depends(get_clock),
) -> RescanResponse:
    """Run one watcher pass synchronously.

    Pragmatic deviation: the API runs a dedicated ``StabilityWatcher``
    instance with ``stability_window_seconds=0`` and primes its in-memory
    observation table with a no-op pass before doing the actual enqueue
    pass. The watcher requires two observations to consider a file
    stable; this hand-shake is the operator-triggered "I know this file
    is ready" hook on top of that contract.
    """
    overrides_ingestion = settings.ingestion.model_copy(update={"stability_window_seconds": 0.0})

    enqueued: int = 0
    with factory() as session:
        watcher = StabilityWatcher(
            input_dir=Path(settings.paths.input_dir),
            ingestion=overrides_ingestion,
            pipeline_version=settings.runtime.pipeline_version,
            clock=clock,
            files=SqlFileRepository(session),
            jobs=SqlJobRepository(session),
            events=SqlJobEventRepository(session),
            snapshots=SqlConfigSnapshotRepository(session),
            snapshot_factory=lambda: settings_to_config_snapshot(settings),
        )
        # First scan: register every candidate file in the observation
        # table but enqueue nothing (the watcher contract requires an
        # initial observation point). Second scan with the same clock and
        # zero stability window enqueues every newly stable file.
        watcher.scan_once()
        result = watcher.scan_once()
        session.commit()
        enqueued = len(result.enqueued_jobs)

    logger.info("rescan: enqueued=%d", enqueued)
    return RescanResponse(enqueued=enqueued)


@router.post("/{job_id}/retry", response_model=JobSummaryOut)
def retry_job(
    job_id: int,
    session: Session = Depends(get_session),
) -> JobSummaryOut:
    """Move a failed job back to pending so the worker picks it up again."""
    jobs = SqlJobRepository(session)
    current = jobs.get(job_id)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Job not found"},
        )
    if current.status is not JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invalid_state",
                "message": f"Cannot retry job in status {current.status.value}",
            },
        )
    jobs.transition(job_id, new_status=JobStatus.PENDING)
    SqlJobEventRepository(session).append(
        JobEvent(job_id=job_id, type="retry_requested", payload={})
    )
    summary = jobs.get_summary(job_id)
    assert summary is not None
    return JobSummaryOut.model_validate(summary)


@router.post("/{job_id}/reprocess", response_model=JobSummaryOut)
def reprocess_job(
    job_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> JobSummaryOut:
    """Schedule a fresh job for the same file using the current configuration.

    The original job is left untouched; reprocess always creates a new
    ``Job`` row with a freshly computed ``run_key``. If an active job for
    that key already exists (worker still chewing on it), the request is
    rejected with 409.
    """
    jobs = SqlJobRepository(session)
    files = SqlFileRepository(session)
    snapshots = SqlConfigSnapshotRepository(session)
    events = SqlJobEventRepository(session)

    original = jobs.get(job_id)
    if original is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Job not found"},
        )

    file = files.get(original.file_id)
    if file is None or file.id is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "file_missing", "message": "Source file is no longer registered"},
        )

    # Build a snapshot from current settings (overrides are not yet woven
    # in — see ConfigService docstring for the deviation note).
    snapshot_input = settings_to_config_snapshot(settings)
    # Recompute the hash defensively in case payload contents drifted.
    snapshot_input = ConfigSnapshot(
        hash=compute_config_snapshot_hash(snapshot_input.payload),
        ai_backend=snapshot_input.ai_backend,
        ai_mode=snapshot_input.ai_mode,
        ocr_backend=snapshot_input.ocr_backend,
        pipeline_version=snapshot_input.pipeline_version,
        payload=snapshot_input.payload,
    )
    snapshot = snapshots.get_or_create(snapshot_input)
    if snapshot.id is None:
        raise HTTPException(
            status_code=500,
            detail={"code": "snapshot_failed", "message": "Could not persist config snapshot"},
        )

    run_key = compute_run_key(
        file_sha256=file.sha256,
        config_snapshot_hash=snapshot.hash,
        pipeline_version=settings.runtime.pipeline_version,
    )
    if jobs.has_active_with_run_key(run_key):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "already_active",
                "message": "An active job for this file/config already exists",
            },
        )

    new_job = jobs.add(
        Job(
            file_id=file.id,
            status=JobStatus.PENDING,
            mode=snapshot.ai_mode or AiMode.OFF,
            run_key=run_key,
            config_snapshot_id=snapshot.id,
            pipeline_version=settings.runtime.pipeline_version,
        )
    )
    if new_job.id is None:
        raise HTTPException(
            status_code=500,
            detail={"code": "job_failed", "message": "Could not persist new job"},
        )

    events.append(
        JobEvent(
            job_id=new_job.id,
            type=JobEventType.ENQUEUED.value,
            payload={
                "source": "reprocess",
                "previous_job_id": job_id,
                "run_key": run_key,
                "snapshot_id": snapshot.id,
                "snapshot_hash": snapshot.hash,
            },
        )
    )

    summary = jobs.get_summary(new_job.id)
    assert summary is not None
    return JobSummaryOut.model_validate(summary)


# Suppress unused-import linter complaint for AiBackend / OcrBackend which
# are only imported so they round-trip through enum validation in DTOs.
_ = (AiBackend, OcrBackend)
