"""/history endpoints.

History = exported document parts. Each entry shows where the part went
(``output_name``/``output_path``), its provenance (file + job), and its
deterministic hash so operators can correlate with paperless ingest.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...config import Settings
from ...core.ports.clock import ClockPort
from ...storage.db import SqlDocumentPartRepository
from ..deps import get_app_settings, get_clock, get_session
from ..schemas.history import HistoryEntryOut, HistoryListResponse
from ..schemas.review import ReopenResponseOut
from ..services import ReviewService, ReviewServiceError

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryListResponse)
def list_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> HistoryListResponse:
    entries, total = SqlDocumentPartRepository(session).list_history(
        limit=limit,
        offset=offset,
    )
    return HistoryListResponse(
        items=[HistoryEntryOut.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{part_id}", response_model=HistoryEntryOut)
def get_history_entry(part_id: int, session: Session = Depends(get_session)) -> HistoryEntryOut:
    entry = SqlDocumentPartRepository(session).get_history_entry(part_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "History entry not found"},
        )
    return HistoryEntryOut.model_validate(entry)


@router.post(
    "/{part_id}/reopen",
    response_model=ReopenResponseOut,
    status_code=status.HTTP_200_OK,
)
def reopen_history_part(
    part_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    clock: ClockPort = Depends(get_clock),
) -> ReopenResponseOut:
    """Reopen an already-exported part for re-review.

    Creates (or reopens) a single ``ReviewItem`` for the part and
    transitions the owning job from ``COMPLETED`` to ``REVIEW_REQUIRED``
    via the audited ``history_reopen`` transition.
    """
    service = ReviewService(session=session, settings=settings, clock=clock)
    try:
        result = service.reopen_history(part_id)
    except ReviewServiceError as exc:
        code_to_status = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "already_open": status.HTTP_409_CONFLICT,
        }
        raise HTTPException(
            status_code=code_to_status.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ReopenResponseOut(
        review_item_id=result.review_item_id,
        part_id=result.part_id,
        job_id=result.job_id,
    )
