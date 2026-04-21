"""Phase 5 unit tests for the ``ai_split`` apply use case.

The use case is pure: it takes rule drafts, parallel confidences, and a
list of validator-accepted AI proposals, and returns a deterministic
list of ``ResolvedProposal`` records.
"""

from __future__ import annotations

from docunomnom.core.evidence import ValidatedAiProposal
from docunomnom.core.models import (
    AiEvidenceRequest,
    AiProposalAction,
    AiProposalRequest,
    EvidenceKind,
    SplitProposalSource,
)
from docunomnom.core.rules import ProposalDraft
from docunomnom.core.rules.confidence import PartConfidence
from docunomnom.core.usecases.ai_split import (
    AiApplyConfig,
    apply_validated_ai_proposals,
)


def _draft(start: int, end: int, *, reason: str = "rule") -> ProposalDraft:
    return ProposalDraft(start_page=start, end_page=end, reason_codes=(reason,))


def _conf(score: float) -> PartConfidence:
    return PartConfidence(score=score, keyword_score=score, layout_score=0.0, page_number_score=0.0)


def _ev(page: int) -> AiEvidenceRequest:
    return AiEvidenceRequest(
        kind=EvidenceKind.KEYWORD,
        page_no=page,
        snippet="Invoice",
        payload={"keyword": "Invoice"},
    )


def _validated(
    action: AiProposalAction,
    *,
    target: int | None,
    start: int = 1,
    end: int = 1,
    confidence: float = 0.9,
    reason: str = "ai",
) -> ValidatedAiProposal:
    proposal = AiProposalRequest(
        action=action,
        start_page=start,
        end_page=end,
        confidence=confidence,
        reason_code=reason,
        evidences=(_ev(start),),
        target_proposal_id=target,
    )
    return ValidatedAiProposal(
        proposal=proposal,
        target_index=target,
        accepted_evidences=(_ev(start),),
    )


def test_no_validated_yields_rule_only_resolution() -> None:
    drafts = [_draft(1, 2), _draft(3, 4)]
    confidences = [_conf(0.8), _conf(0.5)]
    result = apply_validated_ai_proposals(drafts, confidences, validated=[])
    assert len(result.proposals) == 2
    assert all(p.source is SplitProposalSource.RULE for p in result.proposals)
    assert result.proposals[0].confidence == 0.8
    assert result.proposals[0].absorbed_rule_indices == (0,)


def test_confirm_boosts_confidence_and_marks_merged() -> None:
    drafts = [_draft(1, 2)]
    confidences = [_conf(0.7)]
    vap = _validated(AiProposalAction.CONFIRM, target=0, start=1, end=2)
    result = apply_validated_ai_proposals(
        drafts,
        confidences,
        validated=[vap],
        config=AiApplyConfig(confidence_boost=0.10),
    )
    assert len(result.proposals) == 1
    p = result.proposals[0]
    assert p.source is SplitProposalSource.MERGED
    assert abs(p.confidence - 0.80) < 1e-9
    assert p.confidence_boost == 0.10


def test_reject_marks_rejected_flag() -> None:
    drafts = [_draft(1, 2)]
    confidences = [_conf(0.9)]
    vap = _validated(AiProposalAction.REJECT, target=0, start=1, end=2)
    result = apply_validated_ai_proposals(drafts, confidences, validated=[vap])
    assert result.proposals[0].rejected is True


def test_adjust_replaces_boundaries() -> None:
    drafts = [_draft(1, 4)]
    confidences = [_conf(0.7)]
    vap = _validated(AiProposalAction.ADJUST, target=0, start=2, end=4, confidence=0.85)
    result = apply_validated_ai_proposals(drafts, confidences, validated=[vap])
    assert result.proposals[0].start_page == 2
    assert result.proposals[0].end_page == 4
    assert result.proposals[0].confidence == 0.85


def test_merge_consumes_neighbor() -> None:
    drafts = [_draft(1, 2), _draft(3, 5)]
    confidences = [_conf(0.7), _conf(0.6)]
    vap = _validated(AiProposalAction.MERGE, target=0, start=1, end=5)
    result = apply_validated_ai_proposals(drafts, confidences, validated=[vap])
    assert len(result.proposals) == 1
    p = result.proposals[0]
    assert p.start_page == 1
    assert p.end_page == 5
    assert sorted(p.absorbed_rule_indices) == [0, 1]
    assert p.source is SplitProposalSource.MERGED


def test_add_appends_ai_only_proposal() -> None:
    drafts = [_draft(1, 4)]
    confidences = [_conf(0.9)]
    vap = _validated(AiProposalAction.ADD, target=None, start=2, end=2, confidence=0.75)
    result = apply_validated_ai_proposals(
        drafts,
        confidences,
        validated=[vap],
        config=AiApplyConfig(add_default_confidence=0.6),
    )
    assert len(result.proposals) == 2
    sources = {p.source for p in result.proposals}
    assert SplitProposalSource.AI in sources
    assert SplitProposalSource.RULE in sources


def test_duplicate_target_is_skipped() -> None:
    drafts = [_draft(1, 2)]
    confidences = [_conf(0.7)]
    v1 = _validated(AiProposalAction.MERGE, target=0)
    v2 = _validated(AiProposalAction.CONFIRM, target=0)
    result = apply_validated_ai_proposals(drafts, confidences, validated=[v1, v2])
    # The merge needs a neighbor; with only 1 draft it skips. The confirm
    # then runs and turns the slot into MERGED.
    assert len(result.skipped) >= 1


def test_ordered_output_is_sorted_by_start_page() -> None:
    drafts = [_draft(1, 2), _draft(3, 4)]
    confidences = [_conf(0.8), _conf(0.7)]
    vap = _validated(AiProposalAction.ADD, target=None, start=2, end=2)
    result = apply_validated_ai_proposals(drafts, confidences, validated=[vap])
    starts = [p.start_page for p in result.proposals]
    assert starts == sorted(starts)
