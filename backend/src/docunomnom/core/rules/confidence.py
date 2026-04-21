"""Rule-only confidence aggregation (Phase 2).

Combines per-evidence subscores from a single ``ProposalDraft`` into a single
``confidence`` value in [0, 1] and decides ``DocumentPartDecision`` based on
the configured ``auto_export_threshold``.

AI-derived signals are intentionally NOT consumed here; they will be folded
into a wider aggregator in Phase 5 (after the Evidence Validator lands).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.types import DocumentPartDecision
from .keyword_splitter import ProposalDraft


@dataclass(frozen=True, slots=True)
class ConfidenceWeights:
    """Weights for the three deterministic evidence sources we score on."""

    keyword: float = 0.6
    layout: float = 0.2
    page_number: float = 0.2

    def normalized(self) -> ConfidenceWeights:
        total = self.keyword + self.layout + self.page_number
        if total <= 0:
            return ConfidenceWeights(keyword=1.0, layout=0.0, page_number=0.0)
        return ConfidenceWeights(
            keyword=self.keyword / total,
            layout=self.layout / total,
            page_number=self.page_number / total,
        )


@dataclass(frozen=True, slots=True)
class PartConfidence:
    """Final confidence and a per-source breakdown for one proposal."""

    score: float
    keyword_score: float
    layout_score: float
    page_number_score: float


def aggregate_part_confidence(
    draft: ProposalDraft,
    weights: ConfidenceWeights,
) -> PartConfidence:
    """Combine evidence subscores into a single 0..1 confidence."""
    w = weights.normalized()
    keyword_score = draft.keyword_hit.score if draft.keyword_hit else 0.0

    cue = draft.page_number_hint
    page_number_score = 1.0 if (cue is not None and cue.looks_like_document_start) else 0.0

    # Phase 2 has no real layout-only signal yet (no PDF coordinate access).
    # We treat a present-but-non-start page-number cue as a weak layout
    # signal so the slot is honest rather than always zero.
    layout_score = 0.0
    if cue is not None and not cue.looks_like_document_start:
        layout_score = 0.25

    # The very first page of a document with no other evidence still gets a
    # baseline so a clean single-document file is auto-exportable.
    if draft.reason_codes and "first_page" in draft.reason_codes:
        keyword_score = max(keyword_score, 0.5)

    score = min(
        1.0,
        w.keyword * keyword_score + w.layout * layout_score + w.page_number * page_number_score,
    )
    return PartConfidence(
        score=score,
        keyword_score=keyword_score,
        layout_score=layout_score,
        page_number_score=page_number_score,
    )


def decide_part_decision(
    confidence: PartConfidence,
    *,
    auto_export_threshold: float,
) -> DocumentPartDecision:
    """Map a confidence to a part decision (rule-only)."""
    if confidence.score >= auto_export_threshold:
        return DocumentPartDecision.AUTO_EXPORT
    return DocumentPartDecision.REVIEW_REQUIRED
