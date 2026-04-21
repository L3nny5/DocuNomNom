"""DTOs for the /history endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ...core.models import DocumentPartDecision
from .common import Page


class HistoryEntryOut(BaseModel):
    """One exported document part, joined with its source file metadata."""

    model_config = ConfigDict(from_attributes=True)

    part_id: int
    job_id: int
    file_id: int
    file_name: str
    start_page: int
    end_page: int
    decision: DocumentPartDecision
    confidence: float
    output_name: str | None = None
    output_path: str | None = None
    sha256: str | None = None
    exported_at: datetime | None = None


HistoryListResponse = Page[HistoryEntryOut]
