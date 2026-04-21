"""/review endpoints (Phase 4 minimal review workflow).

Listing, detail, marker replacement, finalize, and a range-friendly PDF
stream. The router only does request-shape concerns; all real work is
delegated to :class:`docunomnom.api.services.ReviewService`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ...config import Settings
from ...core.models import (
    ReviewItemStatus,
    ReviewMarker,
    ReviewMarkerKind,
    SplitProposal,
)
from ...core.ports.clock import ClockPort
from ...storage.db import (
    SqlReviewItemRepository,
    SqlReviewMarkerRepository,
    SqlSplitProposalRepository,
)
from ...storage.files import UnsafePathError, safe_path
from ..deps import get_app_settings, get_clock, get_session
from ..schemas.review import (
    FinalizeResultOut,
    MarkerSetIn,
    ReviewItemDetailOut,
    ReviewItemSummaryOut,
    ReviewListResponse,
    ReviewMarkerOut,
    SplitProposalOut,
)
from ..services import ReviewService, ReviewServiceError

router = APIRouter(prefix="/review", tags=["review"])

logger = logging.getLogger(__name__)

# Streamed PDF chunk size; small enough to keep memory flat, large enough
# to amortize syscall cost on local SSDs.
_STREAM_CHUNK = 256 * 1024


def _service(
    session: Session,
    settings: Settings,
    clock: ClockPort,
) -> ReviewService:
    return ReviewService(session=session, settings=settings, clock=clock)


def _raise_for_service_error(exc: ReviewServiceError) -> None:
    code_to_status = {
        "not_found": status.HTTP_404_NOT_FOUND,
        "already_done": status.HTTP_409_CONFLICT,
        "already_open": status.HTTP_409_CONFLICT,
        "invalid_marker": status.HTTP_400_BAD_REQUEST,
        "invalid_markers": status.HTTP_400_BAD_REQUEST,
        "pdf_missing": status.HTTP_409_CONFLICT,
        "pdf_split_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "export_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "part_persist_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "export_persist_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
    http_status = code_to_status.get(exc.code, status.HTTP_400_BAD_REQUEST)
    raise HTTPException(
        status_code=http_status,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("", response_model=ReviewListResponse)
def list_review_items(
    status_filter: ReviewItemStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ReviewListResponse:
    """List review items, optionally filtered by status (default all).

    Open items (``OPEN`` and ``IN_PROGRESS``) are the operator's normal
    inbox; ``DONE`` is exposed for traceability.
    """
    items, total = SqlReviewItemRepository(session).list_summaries(
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return ReviewListResponse(
        items=[ReviewItemSummaryOut.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{item_id}", response_model=ReviewItemDetailOut)
def get_review_item(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> ReviewItemDetailOut:
    """Return everything the review screen needs in one round trip."""
    items_repo = SqlReviewItemRepository(session)
    summary = items_repo.get_summary(item_id)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "ReviewItem not found"},
        )

    markers = SqlReviewMarkerRepository(session).list_for_item(item_id)
    proposals: list[SplitProposal] = SqlSplitProposalRepository(session).list_for_analysis(
        summary.analysis_id
    )

    pdf_url = str(request.url_for("get_review_pdf", item_id=item_id))

    return ReviewItemDetailOut(
        item=ReviewItemSummaryOut.model_validate(summary),
        markers=[ReviewMarkerOut.model_validate(m) for m in markers],
        proposals=[SplitProposalOut.model_validate(p) for p in proposals],
        pdf_url=pdf_url,
    )


@router.put("/{item_id}/markers", response_model=list[ReviewMarkerOut])
def put_review_markers(
    item_id: int,
    payload: MarkerSetIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    clock: ClockPort = Depends(get_clock),
) -> list[ReviewMarkerOut]:
    """Atomically replace the marker set for ``item_id``.

    The whole-set replacement matches the UI's edit semantics (the page
    rebuilds the list and pushes the result) and avoids the partial-update
    races that PATCH-style endpoints would inherit.
    """
    domain_markers = [
        ReviewMarker(
            review_item_id=item_id,
            page_no=m.page_no,
            kind=m.kind or ReviewMarkerKind.START,
        )
        for m in payload.markers
    ]
    try:
        result = _service(session, settings, clock).replace_markers(item_id, domain_markers)
    except ReviewServiceError as exc:
        _raise_for_service_error(exc)
    return [ReviewMarkerOut.model_validate(m) for m in result]


@router.post(
    "/{item_id}/finalize",
    response_model=FinalizeResultOut,
    status_code=status.HTTP_200_OK,
)
def finalize_review(
    item_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    clock: ClockPort = Depends(get_clock),
) -> FinalizeResultOut:
    """Apply the persisted markers, export the derived sub-parts, and close
    the review item.
    """
    try:
        result = _service(session, settings, clock).finalize(item_id)
    except ReviewServiceError as exc:
        _raise_for_service_error(exc)
    return FinalizeResultOut(
        item_id=result.item_id,
        job_id=result.job_id,
        job_status=result.job_status.value,
        exported_part_ids=result.exported_part_ids,
        derived_count=result.derived_count,
    )


# ---------------------------------------------------------------- PDF

_RANGE_PREFIX = "bytes="


def _parse_range_header(header: str | None, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range ``Range`` header.

    Returns ``(start, end)`` inclusive, or ``None`` if the header is
    absent / malformed / multi-range (not supported in v1).
    """
    if not header or not header.startswith(_RANGE_PREFIX):
        return None
    raw = header[len(_RANGE_PREFIX) :].strip()
    if "," in raw:
        return None
    try:
        start_str, end_str = raw.split("-", 1)
    except ValueError:
        return None
    if start_str == "":
        # Suffix range: last N bytes.
        try:
            n = int(end_str)
        except ValueError:
            return None
        if n <= 0:
            return None
        start = max(0, file_size - n)
        end = file_size - 1
        return start, end
    try:
        start = int(start_str)
    except ValueError:
        return None
    if end_str == "":
        end = file_size - 1
    else:
        try:
            end = int(end_str)
        except ValueError:
            return None
    if start < 0 or end < start or start >= file_size:
        return None
    end = min(end, file_size - 1)
    return start, end


def _iter_file_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(_STREAM_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{item_id}/pdf", name="get_review_pdf")
def get_review_pdf(
    item_id: int,
    range_header: str | None = Header(default=None, alias="Range"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    clock: ClockPort = Depends(get_clock),
) -> Response:
    """Stream the PDF backing a review item.

    Honors single-range ``Range`` requests so the browser PDF viewer can
    seek without downloading the full file. Path safety: the resolved
    file must live inside the configured input/work/archive roots.
    """
    try:
        pdf_path = _service(session, settings, clock).resolve_pdf(item_id)
    except ReviewServiceError as exc:
        _raise_for_service_error(exc)

    allowed_roots = [
        Path(settings.paths.input_dir),
        Path(settings.paths.work_dir),
        Path(settings.paths.archive_dir),
        Path(settings.storage.ocr_artifact_dir),
    ]
    safe = False
    for root in allowed_roots:
        if not root.is_absolute():
            continue
        try:
            safe_path(root, pdf_path)
            safe = True
            break
        except UnsafePathError:
            continue
    if not safe:
        logger.warning("review pdf path outside allowed roots: %s", pdf_path)
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden_path", "message": "PDF path is outside allowed roots"},
        )

    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "pdf_missing", "message": "PDF file not found on disk"},
        )

    file_size = os.path.getsize(pdf_path)
    parsed = _parse_range_header(range_header, file_size)

    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{pdf_path.name}"',
        "Cache-Control": "private, no-store",
    }

    if parsed is None:
        return StreamingResponse(
            _iter_file_range(pdf_path, 0, file_size - 1) if file_size > 0 else iter([b""]),
            media_type="application/pdf",
            headers={**common_headers, "Content-Length": str(file_size)},
        )

    start, end = parsed
    length = end - start + 1
    headers = {
        **common_headers,
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
    }
    return StreamingResponse(
        _iter_file_range(pdf_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="application/pdf",
        headers=headers,
    )
