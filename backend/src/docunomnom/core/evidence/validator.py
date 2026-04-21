"""Evidence Validator (Phase 5).

This is the mandatory anti-hallucination gate every AI-derived or AI-modified
split proposal must pass before it is allowed to influence the confidence /
decision layer (plan §11/§12).

The validator is pure: it does not touch persistence or the network. The
caller supplies the AI proposals, the existing rule proposals, the OCR
data and a small validator config; the validator returns two parallel
lists (accepted, rejected). Rejected proposals are returned with a
machine-readable ``reason_code`` that the worker pipeline persists to
``split_decisions`` as ``actor=ai, action=rejected_by_validator``.

Validator rules (plan §12):

1. Mode/action whitelist — actions outside the active mode's whitelist are
   rejected with ``mode_action_violation``.
2. Refine quantitative bounds (only in ``refine`` mode):
   * ``adjust`` may shift a boundary by at most
     ``refine.max_boundary_shift_pages`` pages.
   * ``merge`` only between *directly* adjacent existing proposals (no gap).
   * Across the analysis at most ``refine.max_changes_per_analysis``
     mutating AI actions (adjust + merge + reject) may be accepted.
3. There must be at least ``evidence.min_evidences_per_proposal`` evidences.
4. Each evidence's ``kind`` must be on the allowed list.
5. ``page_no`` must lie inside the proposed range or directly on its
   boundary.
6. ``kind=keyword`` — keyword must be enabled in the active profile and
   actually present in the OCR text of the referenced page (case
   insensitive).
7. ``kind=ocr_snippet`` — snippet must occur as a substring of the
   referenced page's OCR text (case insensitive).
8. ``kind in {sender_change, layout_break, structural}`` — the referenced
   page (or its neighbor) must carry a layout marker matching the
   evidence kind in ``pages[*].layout``. The plan-required marker is
   any truthy entry in ``layout`` whose key matches the evidence kind
   (e.g. ``layout["layout_break"] = True``) or a structural payload
   ``layout["sender"] != layout_neighbor["sender"]``.
9. ``kind=page_number`` — the referenced page (or its neighbor) must
   carry a page-number cue in ``layout`` (key ``page_number``) that
   resets to ``current=1`` at the proposed boundary.

When the validator pipeline is unable to safely route a region (because
all relevant proposals were rejected) the worker is expected to fall
back to ``review_required`` rather than invent behavior — the validator
itself only judges proposals individually; the worker decides what to do
with the resulting set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.entities import AiEvidenceRequest, AiProposalRequest
from ..models.types import AiMode, AiProposalAction, EvidenceKind

# Action whitelists per mode (plan §11).
_ALLOWED_ACTIONS: dict[AiMode, frozenset[AiProposalAction]] = {
    AiMode.OFF: frozenset(),
    AiMode.VALIDATE: frozenset({AiProposalAction.CONFIRM, AiProposalAction.REJECT}),
    AiMode.REFINE: frozenset(
        {
            AiProposalAction.CONFIRM,
            AiProposalAction.REJECT,
            AiProposalAction.MERGE,
            AiProposalAction.ADJUST,
        }
    ),
    AiMode.ENHANCE: frozenset(
        {
            AiProposalAction.CONFIRM,
            AiProposalAction.REJECT,
            AiProposalAction.MERGE,
            AiProposalAction.ADJUST,
            AiProposalAction.ADD,
        }
    ),
}

# Mutating actions counted against ``refine.max_changes_per_analysis``.
_MUTATING_ACTIONS: frozenset[AiProposalAction] = frozenset(
    {AiProposalAction.ADJUST, AiProposalAction.MERGE, AiProposalAction.REJECT}
)


def allowed_actions_for_mode(mode: AiMode) -> frozenset[AiProposalAction]:
    """Public accessor used by adapters to constrain prompt outputs."""
    return _ALLOWED_ACTIONS[mode]


@dataclass(frozen=True, slots=True)
class ValidatorPageView:
    """Minimal page projection the validator needs.

    Adapters/usecases must build this from ``pages.ocr_text`` /
    ``pages.layout_json`` so the core stays storage-free.
    """

    page_no: int
    text: str
    layout: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExistingProposalView:
    """Subset of a persisted ``SplitProposal`` the validator needs.

    ``index`` is the position in the rule-proposal list and is used as a
    stable handle for AI ``target_proposal_id`` references (the AI
    adapter never sees DB ids).
    """

    index: int
    start_page: int
    end_page: int


@dataclass(frozen=True, slots=True)
class ValidatorConfig:
    """Validator knobs sourced from ``AiSettings``."""

    min_evidences_per_proposal: int = 1
    allowed_kinds: frozenset[EvidenceKind] = frozenset(EvidenceKind)
    max_boundary_shift_pages: int = 1
    max_changes_per_analysis: int = 3


@dataclass(frozen=True, slots=True)
class ValidatedAiProposal:
    """An AI proposal that passed every validator rule."""

    proposal: AiProposalRequest
    target_index: int | None
    accepted_evidences: tuple[AiEvidenceRequest, ...]


@dataclass(frozen=True, slots=True)
class RejectedAiProposal:
    """An AI proposal rejected by the validator.

    ``reason_code`` is one of the stable codes documented in plan §12 and
    is persisted to ``split_decisions.payload['reason_code']``.
    """

    proposal: AiProposalRequest
    reason_code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: tuple[ValidatedAiProposal, ...]
    rejected: tuple[RejectedAiProposal, ...]


def _norm(text: str) -> str:
    return text.lower()


def _page_by_no(pages: list[ValidatorPageView], page_no: int) -> ValidatorPageView | None:
    for p in pages:
        if p.page_no == page_no:
            return p
    return None


def _page_in_range(start: int, end: int, page_no: int) -> bool:
    """A page is in range if it falls inside ``[start..end]`` or sits on a
    boundary directly adjacent (start-1 or end+1)."""
    return (start - 1) <= page_no <= (end + 1)


def _validate_evidence(
    evidence: AiEvidenceRequest,
    *,
    proposal: AiProposalRequest,
    pages: list[ValidatorPageView],
    enabled_keywords: frozenset[str],
    config: ValidatorConfig,
) -> str | None:
    """Return ``None`` if valid, else a stable reason code."""
    if evidence.kind not in config.allowed_kinds:
        return "evidence_kind_not_allowed"

    if evidence.page_no < 1:
        return "evidence_page_invalid"

    if not _page_in_range(proposal.start_page, proposal.end_page, evidence.page_no):
        return "evidence_page_out_of_range"

    page = _page_by_no(pages, evidence.page_no)
    if page is None:
        return "evidence_page_unknown"

    text_norm = _norm(page.text)

    if evidence.kind is EvidenceKind.KEYWORD:
        keyword = str(evidence.payload.get("keyword", "")).strip()
        if not keyword:
            return "evidence_keyword_missing"
        if _norm(keyword) not in enabled_keywords:
            return "evidence_keyword_disabled"
        if _norm(keyword) not in text_norm:
            return "evidence_keyword_not_in_text"
        return None

    if evidence.kind is EvidenceKind.OCR_SNIPPET:
        snippet = (evidence.snippet or "").strip()
        if not snippet:
            return "evidence_snippet_missing"
        if _norm(snippet) not in text_norm:
            return "evidence_snippet_not_in_text"
        return None

    if evidence.kind is EvidenceKind.PAGE_NUMBER:
        # Validate against stored layout cue if available.
        cue = page.layout.get("page_number") if isinstance(page.layout, dict) else None
        if not isinstance(cue, dict):
            return "evidence_page_number_missing"
        try:
            current = int(cue.get("current", 0))
            total = int(cue.get("total", 0))
        except (TypeError, ValueError):
            return "evidence_page_number_invalid"
        if current < 1 or total < 1 or current > total:
            return "evidence_page_number_invalid"
        # On a proposed boundary, current=1 (i.e. a reset/jump) is required.
        on_boundary = evidence.page_no in (proposal.start_page, proposal.start_page - 1)
        if on_boundary and current != 1:
            return "evidence_page_number_no_reset"
        return None

    if evidence.kind in {
        EvidenceKind.LAYOUT_BREAK,
        EvidenceKind.SENDER_CHANGE,
        EvidenceKind.STRUCTURAL,
    }:
        marker_key = evidence.kind.value
        if not isinstance(page.layout, dict):
            return "evidence_layout_missing"
        marker = page.layout.get(marker_key)
        if not marker:
            return "evidence_layout_marker_missing"
        if evidence.kind is EvidenceKind.SENDER_CHANGE:
            neighbor = _page_by_no(pages, evidence.page_no - 1) or _page_by_no(
                pages, evidence.page_no + 1
            )
            if neighbor is None:
                return None
            sender_now = page.layout.get("sender")
            sender_prev = (
                neighbor.layout.get("sender") if isinstance(neighbor.layout, dict) else None
            )
            if sender_now and sender_prev and sender_now == sender_prev:
                return "evidence_sender_unchanged"
        return None

    return "evidence_kind_unsupported"


def _check_refine_bounds(
    proposal: AiProposalRequest,
    *,
    existing: list[ExistingProposalView],
    target_index: int | None,
    config: ValidatorConfig,
) -> str | None:
    """Return reason code if a refine-mode quantitative bound fails."""
    if proposal.action is AiProposalAction.ADJUST:
        if target_index is None:
            return "adjust_target_missing"
        target = next((e for e in existing if e.index == target_index), None)
        if target is None:
            return "adjust_target_unknown"
        shift = max(
            abs(proposal.start_page - target.start_page),
            abs(proposal.end_page - target.end_page),
        )
        if shift > config.max_boundary_shift_pages:
            return "adjust_shift_exceeded"
        return None

    if proposal.action is AiProposalAction.MERGE:
        if target_index is None:
            return "merge_target_missing"
        target = next((e for e in existing if e.index == target_index), None)
        if target is None:
            return "merge_target_unknown"
        # The merge target must directly abut another existing proposal
        # (no gap). The proposed range must span exactly target+next.
        next_neighbor = next(
            (e for e in existing if e.index == target_index + 1),
            None,
        )
        if next_neighbor is None:
            return "merge_no_neighbor"
        if (target.end_page + 1) != next_neighbor.start_page:
            return "merge_neighbor_gap"
        if proposal.start_page != target.start_page or proposal.end_page != next_neighbor.end_page:
            return "merge_range_mismatch"
        return None

    return None


def validate_ai_proposals(
    proposals: list[AiProposalRequest],
    *,
    mode: AiMode,
    existing: list[ExistingProposalView],
    pages: list[ValidatorPageView],
    enabled_keywords: frozenset[str],
    config: ValidatorConfig,
) -> ValidationResult:
    """Run the full validator pipeline.

    The function is order-stable: the input order is preserved across
    accepted/rejected so callers can keep their own indexing.
    """
    if mode is AiMode.OFF:
        # Defense in depth: the worker should not call us at all in OFF.
        return ValidationResult(
            accepted=(),
            rejected=tuple(
                RejectedAiProposal(
                    proposal=p,
                    reason_code="mode_action_violation",
                    detail="ai is off",
                )
                for p in proposals
            ),
        )

    allowed = _ALLOWED_ACTIONS[mode]
    by_index = {e.index: e for e in existing}

    accepted: list[ValidatedAiProposal] = []
    rejected: list[RejectedAiProposal] = []
    accepted_changes = 0

    for proposal in proposals:
        if proposal.action not in allowed:
            rejected.append(
                RejectedAiProposal(
                    proposal=proposal,
                    reason_code="mode_action_violation",
                    detail=f"{proposal.action.value} not allowed in {mode.value}",
                )
            )
            continue

        # Range sanity.
        if proposal.start_page < 1 or proposal.end_page < proposal.start_page:
            rejected.append(
                RejectedAiProposal(
                    proposal=proposal,
                    reason_code="proposal_range_invalid",
                )
            )
            continue

        # Confidence sanity.
        if not 0.0 <= proposal.confidence <= 1.0:
            rejected.append(
                RejectedAiProposal(proposal=proposal, reason_code="confidence_out_of_range")
            )
            continue

        target_index: int | None = proposal.target_proposal_id
        if proposal.action in {
            AiProposalAction.CONFIRM,
            AiProposalAction.REJECT,
            AiProposalAction.ADJUST,
            AiProposalAction.MERGE,
        } and (target_index is None or target_index not in by_index):
            rejected.append(
                RejectedAiProposal(
                    proposal=proposal,
                    reason_code="target_proposal_unknown",
                )
            )
            continue

        # Refine-mode quantitative bounds.
        if mode is AiMode.REFINE:
            bound_violation = _check_refine_bounds(
                proposal,
                existing=existing,
                target_index=target_index,
                config=config,
            )
            if bound_violation is not None:
                rejected.append(
                    RejectedAiProposal(
                        proposal=proposal,
                        reason_code=bound_violation,
                    )
                )
                continue

        # Evidence requirements.
        if len(proposal.evidences) < config.min_evidences_per_proposal:
            rejected.append(
                RejectedAiProposal(
                    proposal=proposal,
                    reason_code="insufficient_evidence",
                )
            )
            continue

        evidence_failure: str | None = None
        for evidence in proposal.evidences:
            failure = _validate_evidence(
                evidence,
                proposal=proposal,
                pages=pages,
                enabled_keywords=enabled_keywords,
                config=config,
            )
            if failure is not None:
                evidence_failure = failure
                break
        if evidence_failure is not None:
            rejected.append(
                RejectedAiProposal(
                    proposal=proposal,
                    reason_code=evidence_failure,
                )
            )
            continue

        # Refine-mode budget for mutating actions.
        if mode is AiMode.REFINE and proposal.action in _MUTATING_ACTIONS:
            if accepted_changes >= config.max_changes_per_analysis:
                rejected.append(
                    RejectedAiProposal(
                        proposal=proposal,
                        reason_code="refine_change_budget_exceeded",
                    )
                )
                continue
            accepted_changes += 1

        accepted.append(
            ValidatedAiProposal(
                proposal=proposal,
                target_index=target_index,
                accepted_evidences=tuple(proposal.evidences),
            )
        )

    return ValidationResult(accepted=tuple(accepted), rejected=tuple(rejected))


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
