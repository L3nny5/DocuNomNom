"""Tests for the rule-only confidence aggregator."""

from __future__ import annotations

from docunomnom.core.features import KeywordHit, PageNumberHint
from docunomnom.core.models import DocumentPartDecision
from docunomnom.core.rules import (
    ConfidenceWeights,
    ProposalDraft,
    aggregate_part_confidence,
    decide_part_decision,
)


def _draft(
    *,
    keyword_score: float | None = None,
    cue_start: bool | None = None,
    reason_codes: tuple[str, ...] = (),
) -> ProposalDraft:
    keyword_hit: KeywordHit | None = None
    if keyword_score is not None:
        keyword_hit = KeywordHit(
            keyword="Invoice",
            page_no=1,
            score=keyword_score,
            snippet="Invoice",
        )
    page_cue: PageNumberHint | None = None
    if cue_start is True:
        page_cue = PageNumberHint(page_no=1, current=1, total=3)
    elif cue_start is False:
        page_cue = PageNumberHint(page_no=1, current=2, total=3)
    return ProposalDraft(
        start_page=1,
        end_page=3,
        keyword_hit=keyword_hit,
        page_number_hint=page_cue,
        reason_codes=reason_codes,
    )


def test_no_evidence_first_page_baseline_above_zero() -> None:
    draft = _draft(reason_codes=("first_page",))
    weights = ConfidenceWeights()
    conf = aggregate_part_confidence(draft, weights)
    # baseline keyword_score=0.5 * keyword_weight 0.6 = 0.30
    assert 0.0 < conf.score <= 0.5
    assert conf.keyword_score == 0.5


def test_strong_keyword_and_page_cue_yields_high_confidence() -> None:
    draft = _draft(keyword_score=1.0, cue_start=True, reason_codes=("keyword_hit",))
    weights = ConfidenceWeights()
    conf = aggregate_part_confidence(draft, weights)
    # 0.6 * 1.0 + 0.2 * 1.0 = 0.8
    assert conf.score >= 0.7


def test_decide_uses_threshold() -> None:
    high = aggregate_part_confidence(
        _draft(keyword_score=1.0, cue_start=True, reason_codes=("keyword_hit",)),
        ConfidenceWeights(),
    )
    low = aggregate_part_confidence(
        _draft(reason_codes=()),
        ConfidenceWeights(),
    )
    assert (
        decide_part_decision(high, auto_export_threshold=0.65) is DocumentPartDecision.AUTO_EXPORT
    )
    assert (
        decide_part_decision(low, auto_export_threshold=0.65)
        is DocumentPartDecision.REVIEW_REQUIRED
    )


def test_weights_normalize_when_sum_not_one() -> None:
    weights = ConfidenceWeights(keyword=2.0, layout=2.0, page_number=0.0).normalized()
    assert abs((weights.keyword + weights.layout + weights.page_number) - 1.0) < 1e-9
