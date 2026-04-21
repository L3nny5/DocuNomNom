"""Phase 5 unit tests for the Evidence Validator.

Covers the mode/action whitelist, evidence kind checks, refine bounds,
and the rejection ``reason_code`` vocabulary documented in plan §12.
"""

from __future__ import annotations

import pytest

from docunomnom.core.evidence import (
    ExistingProposalView,
    ValidatorConfig,
    ValidatorPageView,
    allowed_actions_for_mode,
    validate_ai_proposals,
)
from docunomnom.core.models import (
    AiEvidenceRequest,
    AiMode,
    AiProposalAction,
    AiProposalRequest,
    EvidenceKind,
)


def _proposal(
    action: AiProposalAction,
    *,
    start: int = 1,
    end: int = 1,
    confidence: float = 0.9,
    reason: str = "ai",
    target: int | None = None,
    evidences: tuple[AiEvidenceRequest, ...] = (),
) -> AiProposalRequest:
    return AiProposalRequest(
        action=action,
        start_page=start,
        end_page=end,
        confidence=confidence,
        reason_code=reason,
        evidences=evidences,
        target_proposal_id=target,
    )


def _ev_keyword(page: int, keyword: str) -> AiEvidenceRequest:
    return AiEvidenceRequest(
        kind=EvidenceKind.KEYWORD,
        page_no=page,
        snippet=keyword,
        payload={"keyword": keyword},
    )


def _pages(*texts: str) -> list[ValidatorPageView]:
    return [ValidatorPageView(page_no=i + 1, text=t, layout={}) for i, t in enumerate(texts)]


def _existing(*ranges: tuple[int, int]) -> list[ExistingProposalView]:
    return [
        ExistingProposalView(index=i, start_page=s, end_page=e) for i, (s, e) in enumerate(ranges)
    ]


# ---------------------------------------------------------------------------
# Action whitelist per mode
# ---------------------------------------------------------------------------


def test_off_mode_rejects_everything() -> None:
    proposal = _proposal(AiProposalAction.CONFIRM, target=0)
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.OFF,
        existing=_existing((1, 1)),
        pages=_pages("hello"),
        enabled_keywords=frozenset({"hello"}),
        config=ValidatorConfig(),
    )
    assert len(result.accepted) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason_code == "mode_action_violation"


def test_validate_mode_only_allows_confirm_and_reject() -> None:
    allowed = allowed_actions_for_mode(AiMode.VALIDATE)
    assert allowed == frozenset({AiProposalAction.CONFIRM, AiProposalAction.REJECT})

    add_proposal = _proposal(
        AiProposalAction.ADD,
        start=1,
        end=1,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [add_proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("Invoice text"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "mode_action_violation"


def test_refine_mode_rejects_add_action() -> None:
    add_proposal = _proposal(
        AiProposalAction.ADD,
        start=2,
        end=2,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [add_proposal],
        mode=AiMode.REFINE,
        existing=_existing((1, 2)),
        pages=_pages("a", "Invoice b"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "mode_action_violation"


def test_enhance_mode_allows_add_with_evidence() -> None:
    add_proposal = _proposal(
        AiProposalAction.ADD,
        start=2,
        end=2,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [add_proposal],
        mode=AiMode.ENHANCE,
        existing=_existing((1, 2)),
        pages=_pages("a", "Invoice text"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(min_evidences_per_proposal=1),
    )
    assert len(result.accepted) == 1
    assert result.accepted[0].proposal.action is AiProposalAction.ADD


# ---------------------------------------------------------------------------
# Range / confidence sanity
# ---------------------------------------------------------------------------


def test_invalid_range_is_rejected() -> None:
    proposal = _proposal(
        AiProposalAction.ADJUST,
        start=5,
        end=2,
        target=0,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.REFINE,
        existing=_existing((1, 4)),
        pages=_pages("a", "Invoice", "c", "d"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "proposal_range_invalid"


def test_confidence_out_of_range_is_rejected() -> None:
    proposal = _proposal(
        AiProposalAction.CONFIRM,
        start=1,
        end=1,
        confidence=1.5,
        target=0,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("Invoice"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "confidence_out_of_range"


def test_unknown_target_proposal_is_rejected() -> None:
    proposal = _proposal(
        AiProposalAction.CONFIRM,
        target=99,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("Invoice"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "target_proposal_unknown"


# ---------------------------------------------------------------------------
# Evidence checks
# ---------------------------------------------------------------------------


def test_insufficient_evidence_rejected() -> None:
    proposal = _proposal(AiProposalAction.CONFIRM, target=0, evidences=())
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("text"),
        enabled_keywords=frozenset({"x"}),
        config=ValidatorConfig(min_evidences_per_proposal=1),
    )
    assert result.rejected[0].reason_code == "insufficient_evidence"


def test_keyword_not_in_text_is_rejected() -> None:
    proposal = _proposal(
        AiProposalAction.CONFIRM,
        target=0,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("nothing useful here"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "evidence_keyword_not_in_text"


def test_disabled_keyword_is_rejected() -> None:
    proposal = _proposal(
        AiProposalAction.CONFIRM,
        target=0,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("Invoice text"),
        enabled_keywords=frozenset(),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "evidence_keyword_disabled"


def test_ocr_snippet_must_appear_in_text() -> None:
    snippet = AiEvidenceRequest(
        kind=EvidenceKind.OCR_SNIPPET, page_no=1, snippet="lorem ipsum", payload={}
    )
    bad = _proposal(AiProposalAction.CONFIRM, target=0, evidences=(snippet,))
    result = validate_ai_proposals(
        [bad],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("nothing here"),
        enabled_keywords=frozenset(),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "evidence_snippet_not_in_text"


def test_layout_break_requires_layout_marker() -> None:
    layout_break = AiEvidenceRequest(
        kind=EvidenceKind.LAYOUT_BREAK, page_no=1, snippet=None, payload={}
    )
    proposal = _proposal(AiProposalAction.CONFIRM, target=0, evidences=(layout_break,))
    pages = [ValidatorPageView(page_no=1, text="x", layout={})]
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=pages,
        enabled_keywords=frozenset(),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "evidence_layout_marker_missing"


def test_layout_break_passes_when_marker_present() -> None:
    layout_break = AiEvidenceRequest(
        kind=EvidenceKind.LAYOUT_BREAK, page_no=1, snippet=None, payload={}
    )
    proposal = _proposal(AiProposalAction.CONFIRM, target=0, evidences=(layout_break,))
    pages = [ValidatorPageView(page_no=1, text="x", layout={"layout_break": True})]
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=pages,
        enabled_keywords=frozenset(),
        config=ValidatorConfig(),
    )
    assert len(result.accepted) == 1


def test_evidence_kind_not_allowed() -> None:
    proposal = _proposal(
        AiProposalAction.CONFIRM,
        target=0,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.VALIDATE,
        existing=_existing((1, 1)),
        pages=_pages("Invoice"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(allowed_kinds=frozenset({EvidenceKind.OCR_SNIPPET})),
    )
    assert result.rejected[0].reason_code == "evidence_kind_not_allowed"


# ---------------------------------------------------------------------------
# Refine bounds
# ---------------------------------------------------------------------------


def test_refine_adjust_within_shift_budget() -> None:
    proposal = _proposal(
        AiProposalAction.ADJUST,
        start=2,
        end=4,
        target=0,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.REFINE,
        existing=_existing((1, 4)),
        pages=_pages("a", "Invoice b", "c", "d"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(max_boundary_shift_pages=1),
    )
    assert len(result.accepted) == 1


def test_refine_adjust_exceeds_shift_budget() -> None:
    proposal = _proposal(
        AiProposalAction.ADJUST,
        start=4,
        end=4,
        target=0,
        evidences=(_ev_keyword(4, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.REFINE,
        existing=_existing((1, 4)),
        pages=_pages("a", "b", "c", "Invoice"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(max_boundary_shift_pages=1),
    )
    assert result.rejected[0].reason_code == "adjust_shift_exceeded"


def test_refine_merge_requires_directly_adjacent_neighbor() -> None:
    proposal = _proposal(
        AiProposalAction.MERGE,
        start=1,
        end=4,
        target=0,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.REFINE,
        existing=[
            ExistingProposalView(index=0, start_page=1, end_page=2),
            ExistingProposalView(index=1, start_page=4, end_page=4),
        ],
        pages=_pages("a", "Invoice", "c", "d"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert result.rejected[0].reason_code == "merge_neighbor_gap"


def test_refine_merge_happy_path() -> None:
    proposal = _proposal(
        AiProposalAction.MERGE,
        start=1,
        end=4,
        target=0,
        evidences=(_ev_keyword(2, "Invoice"),),
    )
    result = validate_ai_proposals(
        [proposal],
        mode=AiMode.REFINE,
        existing=[
            ExistingProposalView(index=0, start_page=1, end_page=2),
            ExistingProposalView(index=1, start_page=3, end_page=4),
        ],
        pages=_pages("a", "Invoice", "c", "d"),
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(),
    )
    assert len(result.accepted) == 1


def test_refine_change_budget_enforced() -> None:
    # 3 mutating actions with budget=1 → first accepted, rest rejected.
    p1 = _proposal(
        AiProposalAction.ADJUST,
        start=1,
        end=2,
        target=0,
        evidences=(_ev_keyword(1, "Invoice"),),
    )
    p2 = _proposal(
        AiProposalAction.ADJUST,
        start=3,
        end=4,
        target=1,
        evidences=(_ev_keyword(3, "Invoice"),),
    )
    p3 = _proposal(
        AiProposalAction.ADJUST,
        start=5,
        end=6,
        target=2,
        evidences=(_ev_keyword(5, "Invoice"),),
    )
    pages = _pages("Invoice", "x", "Invoice", "y", "Invoice", "z")
    existing = _existing((1, 2), (3, 4), (5, 6))
    result = validate_ai_proposals(
        [p1, p2, p3],
        mode=AiMode.REFINE,
        existing=existing,
        pages=pages,
        enabled_keywords=frozenset({"invoice"}),
        config=ValidatorConfig(max_changes_per_analysis=1),
    )
    assert len(result.accepted) == 1
    assert len(result.rejected) == 2
    assert all(r.reason_code == "refine_change_budget_exceeded" for r in result.rejected)


@pytest.mark.parametrize(
    "mode,expected",
    [
        (AiMode.OFF, frozenset()),
        (AiMode.VALIDATE, {AiProposalAction.CONFIRM, AiProposalAction.REJECT}),
        (
            AiMode.REFINE,
            {
                AiProposalAction.CONFIRM,
                AiProposalAction.REJECT,
                AiProposalAction.MERGE,
                AiProposalAction.ADJUST,
            },
        ),
        (
            AiMode.ENHANCE,
            {
                AiProposalAction.CONFIRM,
                AiProposalAction.REJECT,
                AiProposalAction.MERGE,
                AiProposalAction.ADJUST,
                AiProposalAction.ADD,
            },
        ),
    ],
)
def test_action_whitelist_per_mode(mode: AiMode, expected: frozenset[AiProposalAction]) -> None:
    assert allowed_actions_for_mode(mode) == frozenset(expected)
