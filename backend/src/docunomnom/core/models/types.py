"""Domain enumerations and small value types.

These mirror the strings used by the v1 schema and API. Using ``StrEnum`` keeps
serialization to JSON / SQL simple while still giving us type safety.
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"


# Statuses that count as "active" for run_key uniqueness.
ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.REVIEW_REQUIRED}
)


class AiMode(StrEnum):
    OFF = "off"
    VALIDATE = "validate"
    REFINE = "refine"
    ENHANCE = "enhance"


class OcrBackend(StrEnum):
    OCRMYPDF = "ocrmypdf"
    EXTERNAL_API = "external_api"


class AiBackend(StrEnum):
    NONE = "none"
    OLLAMA = "ollama"
    OPENAI = "openai"


class SplitProposalSource(StrEnum):
    RULE = "rule"
    AI = "ai"
    MERGED = "merged"


class SplitProposalStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVIEW = "review"


class SplitDecisionActor(StrEnum):
    RULE = "rule"
    AI = "ai"
    USER = "user"


class DocumentPartDecision(StrEnum):
    AUTO_EXPORT = "auto_export"
    REVIEW_REQUIRED = "review_required"
    USER_CONFIRMED = "user_confirmed"


class ReviewItemStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ReviewMarkerKind(StrEnum):
    START = "start"
    REJECT_SPLIT = "reject_split"


class EvidenceKind(StrEnum):
    KEYWORD = "keyword"
    LAYOUT_BREAK = "layout_break"
    SENDER_CHANGE = "sender_change"
    PAGE_NUMBER = "page_number"
    STRUCTURAL = "structural"
    OCR_SNIPPET = "ocr_snippet"


class AiProposalAction(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    MERGE = "merge"
    ADJUST = "adjust"
    ADD = "add"
