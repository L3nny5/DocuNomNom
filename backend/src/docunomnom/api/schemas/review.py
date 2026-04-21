"""DTOs for the /review endpoints (Phase 4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ...core.models import (
    DocumentPartDecision,
    ReviewItemStatus,
    ReviewMarkerKind,
    SplitProposalSource,
)
from .common import Page


class ReviewItemSummaryOut(BaseModel):
    """One row in the review list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    part_id: int
    status: ReviewItemStatus
    job_id: int
    analysis_id: int
    file_id: int
    file_name: str
    start_page: int
    end_page: int
    confidence: float
    decision: DocumentPartDecision
    page_count: int
    finished_at: datetime | None = None


class ReviewMarkerOut(BaseModel):
    """A persisted marker on a review item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    page_no: int = Field(ge=1)
    kind: ReviewMarkerKind
    ts: datetime | None = None


class ReviewMarkerIn(BaseModel):
    """A single marker in a PUT /review/{id}/markers payload."""

    model_config = ConfigDict(extra="forbid")

    page_no: int = Field(ge=1)
    kind: ReviewMarkerKind = ReviewMarkerKind.START


class MarkerSetIn(BaseModel):
    """Whole-set replacement payload for review markers."""

    model_config = ConfigDict(extra="forbid")

    markers: list[ReviewMarkerIn] = Field(default_factory=list)


class SplitProposalOut(BaseModel):
    """Existing split proposal for the review item's analysis."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: SplitProposalSource
    start_page: int
    end_page: int
    confidence: float
    reason_code: str


class ReviewItemDetailOut(BaseModel):
    """GET /review/{id} payload."""

    model_config = ConfigDict(extra="forbid")

    item: ReviewItemSummaryOut
    markers: list[ReviewMarkerOut] = Field(default_factory=list)
    proposals: list[SplitProposalOut] = Field(default_factory=list)
    pdf_url: str


class FinalizeResultOut(BaseModel):
    """POST /review/{id}/finalize payload."""

    model_config = ConfigDict(extra="forbid")

    item_id: int
    job_id: int
    job_status: str
    exported_part_ids: list[int] = Field(default_factory=list)
    derived_count: int = Field(ge=0)


class ReopenResponseOut(BaseModel):
    """POST /history/{part_id}/reopen payload."""

    model_config = ConfigDict(extra="forbid")

    review_item_id: int
    part_id: int
    job_id: int


ReviewListResponse = Page[ReviewItemSummaryOut]
