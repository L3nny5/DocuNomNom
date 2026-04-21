"""Apply validated AI proposals to the rule-only proposal set (Phase 5).

This use case is the deterministic glue between the Evidence Validator
output and the persistence/decision layer. It is intentionally pure (no
DB, no HTTP, no clock) so it can be unit-tested in isolation.

Inputs
------
* ``drafts``: the rule-engine output (``ProposalDraft`` list, one entry
  per current split candidate).
* ``confidences``: parallel list of ``PartConfidence`` produced by the
  rule confidence aggregator.
* ``validated``: AI proposals that already passed the Evidence Validator.

Outputs
-------
A list of ``ResolvedProposal`` records containing the final boundary,
final confidence, source label (``rule`` / ``ai`` / ``merged``) and the
list of rule indices it absorbed. The caller maps these back to
``SplitProposal`` / ``DocumentPart`` rows.

Action semantics (plan §11)
---------------------------
* ``confirm``: nudges the target rule proposal's confidence upward by
  ``confidence_boost`` (capped at 1.0). No boundary change.
* ``reject``: marks the target rule proposal as rejected; the resulting
  region is forced to ``REVIEW_REQUIRED`` regardless of its rule
  confidence.
* ``adjust``: replaces the target rule proposal's start/end with the
  AI-supplied range (the validator already enforced the shift budget).
* ``merge``: replaces two adjacent proposals (target + target+1) with a
  single proposal spanning both ranges.
* ``add``: inserts a brand new AI-only proposal (only valid in
  ``enhance`` mode, the validator enforces that).

Conservative tie-breaking: confirm/reject of the same target collapse
into a single decision favoring the *first* validated entry; subsequent
duplicates are skipped silently. Mergers and adjusts that point at a
target index already consumed by a previous merge/adjust are also
skipped silently. The worker logs an audit event for every skipped
duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..evidence import ValidatedAiProposal
from ..models.entities import AiEvidenceRequest
from ..models.types import AiProposalAction, SplitProposalSource
from ..rules.confidence import PartConfidence
from ..rules.keyword_splitter import ProposalDraft


@dataclass(frozen=True, slots=True)
class ResolvedProposal:
    """One entry in the final proposal set after AI resolution."""

    start_page: int
    end_page: int
    confidence: float
    source: SplitProposalSource
    reason_code: str
    rejected: bool = False
    absorbed_rule_indices: tuple[int, ...] = ()
    evidences: tuple[AiEvidenceRequest, ...] = ()
    confidence_boost: float = 0.0


@dataclass(frozen=True, slots=True)
class AiApplyConfig:
    """Knobs for the apply step."""

    confidence_boost: float = 0.10
    add_default_confidence: float = 0.7


@dataclass(slots=True)
class _Slot:
    """Internal mutable slot mirroring one rule draft + decisions."""

    index: int
    start_page: int
    end_page: int
    confidence: float
    reason_code: str
    source: SplitProposalSource = SplitProposalSource.RULE
    boost: float = 0.0
    rejected: bool = False
    consumed: bool = False
    absorbed: list[int] = field(default_factory=list)
    evidences: list[AiEvidenceRequest] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _AddedSlot:
    """Internal record for an ``add`` action (enhance mode)."""

    proposal_start: int
    proposal_end: int
    confidence: float
    reason_code: str
    evidences: tuple[AiEvidenceRequest, ...]


@dataclass(frozen=True, slots=True)
class AiApplyResult:
    """Output of :func:`apply_validated_ai_proposals`."""

    proposals: tuple[ResolvedProposal, ...]
    skipped: tuple[tuple[ValidatedAiProposal, str], ...] = ()


def _seed_slots(
    drafts: list[ProposalDraft],
    confidences: list[PartConfidence],
) -> list[_Slot]:
    out: list[_Slot] = []
    for idx, (draft, conf) in enumerate(zip(drafts, confidences, strict=True)):
        out.append(
            _Slot(
                index=idx,
                start_page=draft.start_page,
                end_page=draft.end_page,
                confidence=conf.score,
                reason_code=",".join(draft.reason_codes) or "rule",
                absorbed=[idx],
            )
        )
    return out


def apply_validated_ai_proposals(
    drafts: list[ProposalDraft],
    confidences: list[PartConfidence],
    *,
    validated: list[ValidatedAiProposal],
    config: AiApplyConfig | None = None,
) -> AiApplyResult:
    """Resolve a final proposal list from drafts + validated AI proposals."""
    cfg = config or AiApplyConfig()
    slots = _seed_slots(drafts, confidences)
    by_index = {slot.index: slot for slot in slots}
    skipped: list[tuple[ValidatedAiProposal, str]] = []
    added: list[_AddedSlot] = []

    for vap in validated:
        action = vap.proposal.action
        target_index = vap.target_index

        if action is AiProposalAction.CONFIRM:
            slot = by_index.get(target_index) if target_index is not None else None
            if slot is None or slot.consumed or slot.rejected:
                skipped.append((vap, "target_unavailable"))
                continue
            slot.boost = min(1.0, slot.boost + cfg.confidence_boost)
            slot.confidence = min(1.0, slot.confidence + cfg.confidence_boost)
            if slot.source is SplitProposalSource.RULE:
                slot.source = SplitProposalSource.MERGED
            slot.evidences.extend(vap.accepted_evidences)
            continue

        if action is AiProposalAction.REJECT:
            slot = by_index.get(target_index) if target_index is not None else None
            if slot is None or slot.consumed:
                skipped.append((vap, "target_unavailable"))
                continue
            slot.rejected = True
            slot.source = SplitProposalSource.MERGED
            slot.evidences.extend(vap.accepted_evidences)
            continue

        if action is AiProposalAction.ADJUST:
            slot = by_index.get(target_index) if target_index is not None else None
            if slot is None or slot.consumed or slot.rejected:
                skipped.append((vap, "target_unavailable"))
                continue
            slot.start_page = vap.proposal.start_page
            slot.end_page = vap.proposal.end_page
            slot.confidence = min(1.0, max(slot.confidence, vap.proposal.confidence))
            slot.source = SplitProposalSource.MERGED
            slot.evidences.extend(vap.accepted_evidences)
            continue

        if action is AiProposalAction.MERGE:
            if target_index is None:
                skipped.append((vap, "target_unavailable"))
                continue
            slot = by_index.get(target_index)
            neighbor = by_index.get(target_index + 1)
            if slot is None or neighbor is None or slot.consumed or neighbor.consumed:
                skipped.append((vap, "target_unavailable"))
                continue
            slot.end_page = neighbor.end_page
            slot.confidence = min(
                1.0, max(slot.confidence, neighbor.confidence, vap.proposal.confidence)
            )
            slot.source = SplitProposalSource.MERGED
            slot.absorbed.extend(neighbor.absorbed)
            slot.evidences.extend(vap.accepted_evidences)
            neighbor.consumed = True
            continue

        if action is AiProposalAction.ADD:
            added.append(
                _AddedSlot(
                    proposal_start=vap.proposal.start_page,
                    proposal_end=vap.proposal.end_page,
                    confidence=max(cfg.add_default_confidence, vap.proposal.confidence),
                    reason_code=vap.proposal.reason_code or "ai_add",
                    evidences=vap.accepted_evidences,
                )
            )
            continue

        skipped.append((vap, "unsupported_action"))

    out: list[ResolvedProposal] = []
    for slot in slots:
        if slot.consumed:
            continue
        out.append(
            ResolvedProposal(
                start_page=slot.start_page,
                end_page=slot.end_page,
                confidence=slot.confidence,
                source=slot.source,
                reason_code=slot.reason_code,
                rejected=slot.rejected,
                absorbed_rule_indices=tuple(slot.absorbed),
                evidences=tuple(slot.evidences),
                confidence_boost=slot.boost,
            )
        )

    for added_slot in added:
        out.append(
            ResolvedProposal(
                start_page=added_slot.proposal_start,
                end_page=added_slot.proposal_end,
                confidence=added_slot.confidence,
                source=SplitProposalSource.AI,
                reason_code=added_slot.reason_code,
                rejected=False,
                absorbed_rule_indices=(),
                evidences=added_slot.evidences,
                confidence_boost=0.0,
            )
        )

    out.sort(key=lambda p: (p.start_page, p.end_page))
    return AiApplyResult(proposals=tuple(out), skipped=tuple(skipped))


__all__ = [
    "AiApplyConfig",
    "AiApplyResult",
    "ResolvedProposal",
    "apply_validated_ai_proposals",
]
