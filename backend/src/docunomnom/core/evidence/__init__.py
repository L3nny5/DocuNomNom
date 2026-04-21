"""Evidence Validator (mandatory anti-hallucination gate for AI proposals).

Phase 5 implementation. The validator enforces:

* mode-specific action whitelist (off / validate / refine / enhance),
* refine quantitative bounds (max_boundary_shift_pages, adjacent merge,
  max_changes_per_analysis),
* minimum evidences per proposal,
* per-evidence kind verification against OCR / layout / enabled keywords.
"""

from .validator import (
    ExistingProposalView,
    RejectedAiProposal,
    ValidatedAiProposal,
    ValidationResult,
    ValidatorConfig,
    ValidatorPageView,
    allowed_actions_for_mode,
    validate_ai_proposals,
)

__all__ = [
    "ExistingProposalView",
    "RejectedAiProposal",
    "ValidatedAiProposal",
    "ValidationResult",
    "ValidatorConfig",
    "ValidatorPageView",
    "allowed_actions_for_mode",
    "validate_ai_proposals",
]
