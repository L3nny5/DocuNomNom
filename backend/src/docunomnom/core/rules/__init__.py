"""Deterministic rule-based split detection."""

from .confidence import (
    ConfidenceWeights,
    PartConfidence,
    aggregate_part_confidence,
    decide_part_decision,
)
from .keyword_splitter import (
    PageEvidence,
    ProposalDraft,
    SplitterConfig,
    plan_splits,
)

__all__ = [
    "ConfidenceWeights",
    "PageEvidence",
    "PartConfidence",
    "ProposalDraft",
    "SplitterConfig",
    "aggregate_part_confidence",
    "decide_part_decision",
    "plan_splits",
]
