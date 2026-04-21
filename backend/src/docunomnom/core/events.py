"""Stable event vocabulary for ``JobEvent.type``.

All callers that emit job events should use one of these constants instead of
free-form strings. Keeping the vocabulary in one place lets tests, the
review UI, and operators rely on a stable contract.
"""

from __future__ import annotations

from enum import StrEnum


class JobEventType(StrEnum):
    # Lifecycle
    ENQUEUED = "enqueued"
    LEASED = "leased"
    HEARTBEAT = "heartbeat"
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"

    # OCR
    OCR_STARTED = "ocr_started"
    OCR_COMPLETED = "ocr_completed"
    OCR_FAILED = "ocr_failed"
    EXTERNAL_OCR_CALL = "external_ocr_call"

    # Splitting
    RULES_APPLIED = "rules_applied"
    PARTS_BUILT = "parts_built"

    # AI split (Phase 5)
    AI_CALLED = "ai_called"
    AI_SKIPPED = "ai_skipped"
    AI_PROPOSAL_ACCEPTED = "ai_proposal_accepted"
    AI_PROPOSAL_REJECTED = "ai_proposal_rejected"
    AI_APPLIED = "ai_applied"
    AI_FAILED = "ai_failed"

    # Export / archive
    EXPORT_STARTED = "export_started"
    EXPORT_COMPLETED = "export_completed"
    EXPORT_FAILED = "export_failed"
    ARCHIVED = "archived"


__all__ = ["JobEventType"]
