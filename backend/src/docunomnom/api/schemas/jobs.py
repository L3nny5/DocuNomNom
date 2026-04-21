"""DTOs for the /jobs endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ...core.models import AiMode, JobStatus
from .common import Page


class JobSummaryOut(BaseModel):
    """One row in the jobs listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: int
    file_name: str
    file_sha256: str
    status: JobStatus
    mode: AiMode
    attempt: int
    pipeline_version: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_code: str | None = None
    error_msg: str | None = None


class JobEventOut(BaseModel):
    """Append-only audit entry as exposed by the API."""

    id: int
    job_id: int
    type: str
    ts: datetime | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class JobDetailOut(JobSummaryOut):
    """Detailed view of a single job, including its event log."""

    model_config = ConfigDict(from_attributes=True)

    events: list[JobEventOut] = Field(default_factory=list)


JobListResponse = Page[JobSummaryOut]


class RescanResponse(BaseModel):
    """Outcome of POST /jobs/rescan."""

    enqueued: int = Field(ge=0)
