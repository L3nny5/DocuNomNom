"""Domain entities (frameworkfree dataclasses).

Entities are immutable (``frozen=True``); state transitions are modeled as
functions returning new entities, not mutations. The mapping to/from the ORM
layer happens in ``docunomnom.storage.db.repositories``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .types import (
    AiBackend,
    AiMode,
    AiProposalAction,
    DocumentPartDecision,
    EvidenceKind,
    JobStatus,
    OcrBackend,
    ReviewItemStatus,
    ReviewMarkerKind,
    SplitDecisionActor,
    SplitProposalSource,
    SplitProposalStatus,
)


@dataclass(frozen=True, slots=True)
class File:
    """An ingested PDF on disk. ``sha256`` is *not* unique; reprocessing is
    keyed by ``Job.run_key`` instead (file hash + config snapshot + pipeline
    version)."""

    sha256: str
    original_name: str
    size: int
    mtime: datetime
    source_path: str
    archived_path: str | None = None
    created_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Job:
    """A unit of processing work for a single (file, config, pipeline) tuple."""

    file_id: int
    status: JobStatus
    mode: AiMode
    run_key: str
    config_snapshot_id: int
    pipeline_version: str
    attempt: int = 0
    lease_until: datetime | None = None
    error_code: str | None = None
    error_msg: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class JobEvent:
    """Append-only audit record for everything that happens to a job."""

    job_id: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Immutable snapshot of the active processing configuration.

    The ``hash`` is a deterministic digest of ``payload`` and is used as a
    component of ``Job.run_key`` so the same file can be reprocessed under a
    new configuration without colliding with previous jobs.
    """

    hash: str
    ai_backend: AiBackend
    ai_mode: AiMode
    ocr_backend: OcrBackend
    pipeline_version: str
    payload: dict[str, Any] = field(default_factory=dict)
    profile_id: int | None = None
    created_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Analysis:
    """Result envelope produced for a single job."""

    job_id: int
    ocr_backend: OcrBackend
    ai_backend: AiBackend
    ai_mode: AiMode
    page_count: int
    ocr_artifact_path: str | None = None
    created_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Page:
    """A single OCR'd page of an analysis. Long OCR text spills to disk; in
    that case ``text`` holds a truncated version and ``text_truncated`` is
    True."""

    analysis_id: int
    page_no: int
    text: str
    text_truncated: bool = False
    layout: dict[str, Any] = field(default_factory=dict)
    hash: str = ""
    id: int | None = None


@dataclass(frozen=True, slots=True)
class SplitProposal:
    """A candidate split (start/end page) produced by the rule engine or AI."""

    analysis_id: int
    source: SplitProposalSource
    start_page: int
    end_page: int
    confidence: float
    reason_code: str
    status: SplitProposalStatus = SplitProposalStatus.CANDIDATE
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """Per-proposal evidence required for AI-produced or AI-modified
    proposals. Verified by the Evidence Validator (Phase 5)."""

    proposal_id: int
    kind: EvidenceKind
    page_no: int
    snippet: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True, slots=True)
class SplitDecision:
    """Audit entry for any change applied to a SplitProposal."""

    proposal_id: int
    actor: SplitDecisionActor
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentPart:
    """A consolidated split that becomes either an export or a review item."""

    analysis_id: int
    start_page: int
    end_page: int
    decision: DocumentPartDecision
    confidence: float
    export_id: int | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Export:
    """A successfully exported document part."""

    part_id: int
    output_path: str
    output_name: str
    sha256: str
    exported_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """An open or completed manual review for a DocumentPart."""

    part_id: int
    status: ReviewItemStatus = ReviewItemStatus.OPEN
    reviewer_notes: str | None = None
    finished_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewMarker:
    """A user-placed marker inside a review item."""

    review_item_id: int
    page_no: int
    kind: ReviewMarkerKind
    ts: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class ConfigProfile:
    """A named, persisted set of UI-driven configuration overrides.

    v1 uses a single profile named ``DEFAULT_PROFILE_NAME``. ``json_blob``
    holds the raw override payload submitted via the API; ``hash`` is a
    digest of that payload used by the worker to keep snapshot identity
    deterministic if/when the worker starts honoring overrides.
    """

    name: str
    json_blob: dict[str, Any] = field(default_factory=dict)
    hash: str = ""
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Keyword:
    """A single splitter keyword owned by a ``ConfigProfile``."""

    profile_id: int
    term: str
    locale: str = "en"
    enabled: bool = True
    weight: float = 1.0
    id: int | None = None


@dataclass(frozen=True, slots=True)
class JobSummary:
    """Read-side view of a job joined with its file (for listings)."""

    id: int
    file_id: int
    file_name: str
    file_sha256: str
    status: JobStatus
    mode: AiMode
    attempt: int
    pipeline_version: str
    created_at: datetime | None
    updated_at: datetime | None
    error_code: str | None = None
    error_msg: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewItemSummary:
    """Read-side view of an open review item (joined with part/job/file).

    Used by the review list endpoint so the UI can show enough context to
    pick the next item without a follow-up round trip.
    """

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


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Read-side view of a completed/exported document part for history."""

    part_id: int
    job_id: int
    file_id: int
    file_name: str
    start_page: int
    end_page: int
    decision: DocumentPartDecision
    confidence: float
    output_name: str | None
    output_path: str | None
    sha256: str | None
    exported_at: datetime | None


@dataclass(frozen=True, slots=True)
class AiEvidenceRequest:
    """Evidence as supplied by an AI adapter, before persistence.

    The Evidence Validator (Phase 5) consumes this shape and either accepts
    or rejects the proposal. Defined here so the adapter contract is stable
    from Phase 1 onward.
    """

    kind: EvidenceKind
    page_no: int
    snippet: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AiProposalRequest:
    """An AI-proposed action against an existing or new split, plus the
    evidence required to justify it."""

    action: AiProposalAction
    start_page: int
    end_page: int
    confidence: float
    reason_code: str
    evidences: tuple[AiEvidenceRequest, ...] = ()
    target_proposal_id: int | None = None


DEFAULT_PROFILE_NAME = "default"


__all__ = [
    "DEFAULT_PROFILE_NAME",
    "AiEvidenceRequest",
    "AiProposalRequest",
    "Analysis",
    "ConfigProfile",
    "ConfigSnapshot",
    "DocumentPart",
    "Evidence",
    "Export",
    "File",
    "HistoryEntry",
    "Job",
    "JobEvent",
    "JobSummary",
    "Keyword",
    "Page",
    "ReviewItem",
    "ReviewItemSummary",
    "ReviewMarker",
    "SplitDecision",
    "SplitProposal",
]
