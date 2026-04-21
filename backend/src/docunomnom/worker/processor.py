"""Phase 2 job processor.

Wires the deterministic Phase 2 pipeline together:

1. Lazily load the ``File`` for the leased ``Job``.
2. Run OCR via ``OcrPort`` (OCRmyPDF or generic external API, picked from
   settings).
3. Persist ``Analysis`` and per-page text/layout into the database, with a
   small inline budget that spills to disk for very large pages.
4. Extract per-page features (keyword hits, page-number cues).
5. Run the rule-based splitter and aggregate confidence per draft.
6. Persist ``SplitProposal`` rows (rule-only, auto-approved) plus their
   ``Evidence``.
7. Persist ``DocumentPart`` rows with ``AUTO_EXPORT`` /
   ``REVIEW_REQUIRED`` decisions.
8. Atomically export every ``AUTO_EXPORT`` part into the output directory.
9. Optionally archive the original PDF (only when *all* parts were
   auto-exported, so review still has access to the source).
10. Decide outcome: ``COMPLETED`` iff every part was auto-exported, else
    ``REVIEW_REQUIRED``.

Each step is wrapped in a ``heartbeat()`` call so the loop keeps the lease
alive on long OCR runs. The processor opens its own database session via
the supplied ``session_factory``; commit happens once at the very end so a
crash leaves no half-persisted analysis.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..core.events import JobEventType
from ..core.evidence import (
    ExistingProposalView,
    RejectedAiProposal,
    ValidatedAiProposal,
    ValidationResult,
    ValidatorConfig,
    ValidatorPageView,
    validate_ai_proposals,
)
from ..core.features import detect_page_number_hint, find_keyword_hits
from ..core.models import (
    AiBackend,
    AiMode,
    Analysis,
    DocumentPart,
    DocumentPartDecision,
    Evidence,
    EvidenceKind,
    Job,
    JobEvent,
    JobStatus,
    Page,
    ReviewItem,
    ReviewItemStatus,
    SplitDecision,
    SplitDecisionActor,
    SplitProposal,
    SplitProposalSource,
    SplitProposalStatus,
)
from ..core.ports.ai_split import AiSplitPort
from ..core.ports.ocr import OcrPort, OcrResult
from ..core.rules import (
    ConfidenceWeights,
    PageEvidence,
    PartConfidence,
    ProposalDraft,
    SplitterConfig,
    aggregate_part_confidence,
    plan_splits,
)
from ..core.usecases.ai_split import (
    AiApplyConfig,
    ResolvedProposal,
    apply_validated_ai_proposals,
)
from ..storage.db.repositories import (
    SqlAnalysisRepository,
    SqlDocumentPartRepository,
    SqlEvidenceRepository,
    SqlExportRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlPageRepository,
    SqlReviewItemRepository,
    SqlSplitDecisionRepository,
    SqlSplitProposalRepository,
)
from ..storage.files import (
    archive_original,
    artifact_path_for_job,
    atomic_publish,
    decide_page_text_storage,
)
from .loop import JobOutcome, JobProcessingError

logger = logging.getLogger(__name__)


OcrPortFactory = Callable[[Path, Callable[[str, dict[str, Any]], None]], OcrPort]
AiSplitPortFactory = Callable[[Callable[[str, dict[str, Any]], None]], AiSplitPort]


def _default_ai_factory(_cb: Callable[[str, dict[str, Any]], None]) -> AiSplitPort:
    from ..adapters.ai_split import NoneAiSplitAdapter

    return NoneAiSplitAdapter()


@dataclass(frozen=True, slots=True)
class AiStepOutcome:
    """Combined output of the optional AI step.

    ``ai_called`` is False when AI was disabled or short-circuited; in that
    case ``resolved`` mirrors the rule-only drafts byte-for-byte.
    """

    resolved: tuple[ResolvedProposal, ...]
    accepted_count: int
    rejected_count: int
    ai_called: bool
    accepted: tuple[ValidatedAiProposal, ...] = ()
    rejected: tuple[RejectedAiProposal, ...] = ()
    ai_failure: str | None = None


def _seed_rule_resolution(
    drafts: list[ProposalDraft],
    confidences: list[PartConfidence],
) -> tuple[ResolvedProposal, ...]:
    """Build the rule-only resolution used when AI is off."""
    return tuple(
        ResolvedProposal(
            start_page=d.start_page,
            end_page=d.end_page,
            confidence=c.score,
            source=SplitProposalSource.RULE,
            reason_code=",".join(d.reason_codes) or "rule",
            rejected=False,
            absorbed_rule_indices=(i,),
            evidences=(),
            confidence_boost=0.0,
        )
        for i, (d, c) in enumerate(zip(drafts, confidences, strict=True))
    )


@dataclass(slots=True)
class Phase2ProcessorConfig:
    """Per-instance settings + factory wiring.

    ``ai_split_port_factory`` is optional; when omitted the processor uses
    the no-op AI adapter so existing rule-only tests (and rule-only
    deployments) keep their previous behavior byte-for-byte.
    """

    settings: Settings
    session_factory: sessionmaker[Session]
    ocr_port_factory: OcrPortFactory
    ai_split_port_factory: AiSplitPortFactory = _default_ai_factory


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Phase2Processor:
    """Concrete processor for the Phase 2 pipeline.

    Constructed once at worker startup and called for every leased job.
    """

    def __init__(self, *, config: Phase2ProcessorConfig) -> None:
        self._config = config

    # ---------------------------------------------------------------- API

    def __call__(
        self,
        job: Job,
        *,
        heartbeat: Callable[[], bool],
    ) -> JobOutcome:
        if job.id is None:
            raise RuntimeError("processor received job without id")
        job_id = job.id

        audit_cb = self._make_audit_callback(job_id)

        with self._open_session() as session:
            file = SqlFileRepository(session).get(job.file_id)
            if file is None or file.id is None:
                raise JobProcessingError("file_missing", f"file {job.file_id} missing")
            file_id = file.id

            self._emit_event(session, job_id, JobEventType.OCR_STARTED, {})
            heartbeat()

            ocr_result = self._run_ocr(
                job_id=job_id,
                source_path=Path(file.source_path),
                audit_cb=audit_cb,
            )
            heartbeat()
            self._emit_event(
                session,
                job_id,
                JobEventType.OCR_COMPLETED,
                {
                    "page_count": len(ocr_result.pages),
                    "artifact_present": ocr_result.artifact_path is not None,
                },
            )

            artifact_path = self._persist_artifact(
                job_id=job_id,
                file_sha256=file.sha256,
                ocr_result=ocr_result,
            )

            analysis = SqlAnalysisRepository(session).add(
                Analysis(
                    job_id=job_id,
                    ocr_backend=self._config.settings.ocr.backend,
                    ai_backend=self._config.settings.ai.backend,
                    ai_mode=self._config.settings.ai.mode,
                    page_count=len(ocr_result.pages),
                    ocr_artifact_path=str(artifact_path) if artifact_path else None,
                )
            )
            if analysis.id is None:
                raise RuntimeError("analysis was not persisted")

            self._persist_pages(session, analysis_id=analysis.id, ocr_result=ocr_result)

            page_evidence = self._build_evidence(ocr_result)
            drafts = plan_splits(
                page_evidence,
                SplitterConfig(
                    min_pages_per_part=self._config.settings.splitter.min_pages_per_part,
                ),
            )
            confidences = [aggregate_part_confidence(d, self._weights()) for d in drafts]
            self._emit_event(
                session,
                job_id,
                JobEventType.RULES_APPLIED,
                {
                    "draft_count": len(drafts),
                    "page_count": len(ocr_result.pages),
                },
            )

            ai_outcome = self._run_ai_step(
                session,
                job_id=job_id,
                drafts=drafts,
                confidences=confidences,
                ocr_result=ocr_result,
                audit_cb=audit_cb,
            )
            resolved = ai_outcome.resolved

            persisted_proposals = self._persist_resolved_proposals_and_evidence(
                session,
                analysis_id=analysis.id,
                drafts=drafts,
                resolved=resolved,
            )
            self._persist_ai_decisions(
                session,
                drafts=drafts,
                resolved=resolved,
                persisted_proposals=persisted_proposals,
                ai_outcome=ai_outcome,
            )
            persisted_parts = self._persist_parts_from_resolved(
                session,
                analysis_id=analysis.id,
                resolved=resolved,
            )
            self._emit_event(
                session,
                job_id,
                JobEventType.PARTS_BUILT,
                {
                    "part_count": len(persisted_parts),
                    "auto_export_count": sum(
                        1 for p in persisted_parts if p.decision is DocumentPartDecision.AUTO_EXPORT
                    ),
                },
            )
            heartbeat()

            # Prefer the persisted artifact path (the OCR'd PDF) since the
            # original ``ocr_result.artifact_path`` may have been moved by
            # ``_persist_artifact`` already. Fall back to the original source
            # PDF when the OCR backend did not produce an artifact.
            split_source = artifact_path if artifact_path is not None else Path(file.source_path)
            all_auto = self._export_parts(
                session,
                job_id=job_id,
                file_original_name=file.original_name,
                resolved=resolved,
                parts=list(persisted_parts),
                split_source_path=split_source,
            )

            # Open one review item per uncertain part so the API can show
            # them immediately. Auto-export parts never get a review item.
            self._open_review_items(session, parts=list(persisted_parts))

            if all_auto and self._config.settings.exporter.archive_after_export:
                archived = archive_original(
                    source_path=Path(file.source_path),
                    archive_dir=Path(self._config.settings.paths.archive_dir),
                    require_same_device=(self._config.settings.exporter.require_same_filesystem),
                )
                SqlFileRepository(session).set_archived_path(file_id, str(archived))
                self._emit_event(
                    session,
                    job_id,
                    JobEventType.ARCHIVED,
                    {"archived_path": str(archived)},
                )

            heartbeat()
            session.commit()

            return JobOutcome(
                status=JobStatus.COMPLETED if all_auto else JobStatus.REVIEW_REQUIRED,
            )

    # -------------------------------------------------------- pipeline pieces

    def _run_ocr(
        self,
        *,
        job_id: int,
        source_path: Path,
        audit_cb: Callable[[str, dict[str, Any]], None],
    ) -> OcrResult:
        job_work_dir = Path(self._config.settings.paths.work_dir) / "ocr" / f"job-{job_id}"
        job_work_dir.mkdir(parents=True, exist_ok=True)
        ocr_port = self._config.ocr_port_factory(job_work_dir, audit_cb)
        try:
            return ocr_port.ocr_pdf(
                str(source_path),
                languages=self._config.settings.ocr.languages,
            )
        except Exception as exc:
            code = getattr(exc, "code", "ocr_failed")
            raise JobProcessingError(str(code), str(exc)) from exc

    def _persist_artifact(
        self,
        *,
        job_id: int,
        file_sha256: str,
        ocr_result: OcrResult,
    ) -> Path | None:
        if not ocr_result.artifact_path:
            return None
        src = Path(ocr_result.artifact_path)
        if not src.exists():
            return None
        target = artifact_path_for_job(
            artifact_root=Path(self._config.settings.storage.ocr_artifact_dir),
            job_id=job_id,
            file_sha256=file_sha256,
            suffix=".ocr.pdf",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            src.replace(target)
        except OSError:
            # Cross-device fallback: copy bytes then unlink.
            target.write_bytes(src.read_bytes())
            try:
                src.unlink()
            except OSError:
                logger.warning("failed to remove staged OCR artifact %s", src)
        return target

    def _persist_pages(
        self,
        session: Session,
        *,
        analysis_id: int,
        ocr_result: OcrResult,
    ) -> None:
        max_inline = self._config.settings.storage.page_text_inline_max_bytes
        pages: list[Page] = []
        for page in ocr_result.pages:
            decision = decide_page_text_storage(page.text, max_inline_bytes=max_inline)
            pages.append(
                Page(
                    analysis_id=analysis_id,
                    page_no=page.page_no,
                    text=decision.db_text,
                    text_truncated=decision.truncated,
                    layout=dict(page.layout),
                    hash=_sha256_bytes(page.text.encode("utf-8")),
                )
            )
        SqlPageRepository(session).add_many(pages)

    def _build_evidence(self, ocr_result: OcrResult) -> list[PageEvidence]:
        keywords = self._config.settings.splitter.keywords
        evidence: list[PageEvidence] = []
        for page in ocr_result.pages:
            kw_hits = tuple(
                find_keyword_hits(
                    page.text,
                    page_no=page.page_no,
                    keywords=keywords,
                )
            )
            cue = detect_page_number_hint(page.text, page_no=page.page_no)
            evidence.append(
                PageEvidence(
                    page_no=page.page_no,
                    keyword_hits=kw_hits,
                    page_number_hint=cue,
                )
            )
        return evidence

    def _weights(self) -> ConfidenceWeights:
        s = self._config.settings.splitter
        return ConfidenceWeights(
            keyword=s.keyword_weight,
            layout=s.layout_weight,
            page_number=s.page_number_weight,
        )

    def _run_ai_step(
        self,
        session: Session,
        *,
        job_id: int,
        drafts: list[ProposalDraft],
        confidences: list[PartConfidence],
        ocr_result: OcrResult,
        audit_cb: Callable[[str, dict[str, Any]], None],
    ) -> AiStepOutcome:
        """Optionally call the AI adapter and run the validator.

        Always returns a deterministic ``AiStepOutcome``. When AI is off
        (mode=off or backend=none) it returns the rule-only resolution.
        """
        ai_settings = self._config.settings.ai
        rule_resolved = _seed_rule_resolution(drafts, confidences)

        if ai_settings.mode is AiMode.OFF or ai_settings.backend is AiBackend.NONE:
            self._emit_event(
                session,
                job_id,
                JobEventType.AI_SKIPPED,
                {"backend": ai_settings.backend.value, "mode": ai_settings.mode.value},
            )
            return AiStepOutcome(
                resolved=rule_resolved,
                accepted_count=0,
                rejected_count=0,
                ai_called=False,
            )

        # Build the existing-proposals view from the rule drafts.
        existing_view = [
            ExistingProposalView(
                index=i,
                start_page=d.start_page,
                end_page=d.end_page,
            )
            for i, d in enumerate(drafts)
        ]
        existing_proposals_for_adapter = tuple(
            SplitProposal(
                analysis_id=0,
                source=SplitProposalSource.RULE,
                start_page=d.start_page,
                end_page=d.end_page,
                confidence=c.score,
                reason_code=",".join(d.reason_codes) or "rule",
                status=SplitProposalStatus.APPROVED,
            )
            for d, c in zip(drafts, confidences, strict=True)
        )

        adapter = self._config.ai_split_port_factory(audit_cb)
        try:
            ai_proposals = adapter.propose(
                mode=ai_settings.mode,
                existing_proposals=existing_proposals_for_adapter,
                ocr=ocr_result,
            )
        except Exception as exc:
            code = getattr(exc, "code", "ai_failed")
            logger.warning("ai split adapter failed: %s (%s)", code, exc)
            self._emit_event(
                session,
                job_id,
                JobEventType.AI_FAILED,
                {"code": str(code), "message": str(exc)},
            )
            # Conservative: route the entire analysis through review by
            # forcing every rule proposal into REVIEW_REQUIRED.
            forced_review = tuple(
                ResolvedProposal(
                    start_page=p.start_page,
                    end_page=p.end_page,
                    confidence=p.confidence,
                    source=p.source,
                    reason_code=p.reason_code,
                    rejected=True,
                    absorbed_rule_indices=p.absorbed_rule_indices,
                    evidences=p.evidences,
                    confidence_boost=0.0,
                )
                for p in rule_resolved
            )
            return AiStepOutcome(
                resolved=forced_review,
                accepted_count=0,
                rejected_count=0,
                ai_called=True,
                ai_failure=str(code),
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

        keywords = frozenset(
            k.strip().lower() for k in self._config.settings.splitter.keywords if k.strip()
        )
        validator_cfg = ValidatorConfig(
            min_evidences_per_proposal=ai_settings.evidence.min_evidences_per_proposal,
            allowed_kinds=frozenset(EvidenceKind(k) for k in ai_settings.evidence.allowed_kinds),
            max_boundary_shift_pages=ai_settings.refine.max_boundary_shift_pages,
            max_changes_per_analysis=ai_settings.refine.max_changes_per_analysis,
        )
        page_views = [
            ValidatorPageView(page_no=p.page_no, text=p.text, layout=dict(p.layout))
            for p in ocr_result.pages
        ]
        validation: ValidationResult = validate_ai_proposals(
            list(ai_proposals),
            mode=ai_settings.mode,
            existing=existing_view,
            pages=page_views,
            enabled_keywords=keywords,
            config=validator_cfg,
        )
        for accepted in validation.accepted:
            self._emit_event(
                session,
                job_id,
                JobEventType.AI_PROPOSAL_ACCEPTED,
                {
                    "action": accepted.proposal.action.value,
                    "target_index": accepted.target_index,
                    "evidence_count": len(accepted.accepted_evidences),
                },
            )
        for rejected in validation.rejected:
            self._emit_event(
                session,
                job_id,
                JobEventType.AI_PROPOSAL_REJECTED,
                {
                    "action": rejected.proposal.action.value,
                    "target_index": rejected.proposal.target_proposal_id,
                    "reason_code": rejected.reason_code,
                },
            )

        apply_result = apply_validated_ai_proposals(
            drafts,
            confidences,
            validated=list(validation.accepted),
            config=AiApplyConfig(),
        )
        self._emit_event(
            session,
            job_id,
            JobEventType.AI_APPLIED,
            {
                "resolved_count": len(apply_result.proposals),
                "skipped_count": len(apply_result.skipped),
            },
        )

        return AiStepOutcome(
            resolved=apply_result.proposals,
            accepted=validation.accepted,
            rejected=validation.rejected,
            accepted_count=len(validation.accepted),
            rejected_count=len(validation.rejected),
            ai_called=True,
        )

    def _persist_resolved_proposals_and_evidence(
        self,
        session: Session,
        *,
        analysis_id: int,
        drafts: list[ProposalDraft],
        resolved: tuple[ResolvedProposal, ...],
    ) -> list[SplitProposal]:
        proposal_rows: list[SplitProposal] = []
        for r in resolved:
            proposal_rows.append(
                SplitProposal(
                    analysis_id=analysis_id,
                    source=r.source,
                    start_page=r.start_page,
                    end_page=r.end_page,
                    confidence=r.confidence,
                    reason_code=r.reason_code,
                    status=(
                        SplitProposalStatus.REJECTED if r.rejected else SplitProposalStatus.APPROVED
                    ),
                )
            )
        persisted = list(SqlSplitProposalRepository(session).add_many(proposal_rows))

        evidences: list[Evidence] = []
        for r, proposal in zip(resolved, persisted, strict=True):
            if proposal.id is None:
                raise RuntimeError("proposal was not persisted")
            for rule_index in r.absorbed_rule_indices:
                if rule_index >= len(drafts):
                    continue
                draft = drafts[rule_index]
                if draft.keyword_hit is not None:
                    hit = draft.keyword_hit
                    evidences.append(
                        Evidence(
                            proposal_id=proposal.id,
                            kind=EvidenceKind.KEYWORD,
                            page_no=hit.page_no,
                            snippet=hit.snippet,
                            payload={"keyword": hit.keyword, "score": hit.score},
                        )
                    )
                if draft.page_number_hint is not None:
                    cue = draft.page_number_hint
                    evidences.append(
                        Evidence(
                            proposal_id=proposal.id,
                            kind=EvidenceKind.PAGE_NUMBER,
                            page_no=cue.page_no,
                            snippet=None,
                            payload={"current": cue.current, "total": cue.total},
                        )
                    )
            for ai_evidence in r.evidences:
                evidences.append(
                    Evidence(
                        proposal_id=proposal.id,
                        kind=ai_evidence.kind,
                        page_no=ai_evidence.page_no,
                        snippet=ai_evidence.snippet,
                        payload=dict(ai_evidence.payload),
                    )
                )
        if evidences:
            SqlEvidenceRepository(session).add_many(evidences)
        return persisted

    def _persist_ai_decisions(
        self,
        session: Session,
        *,
        drafts: list[ProposalDraft],
        resolved: tuple[ResolvedProposal, ...],
        persisted_proposals: list[SplitProposal],
        ai_outcome: AiStepOutcome,
    ) -> None:
        """Append SplitDecision audit rows for accepted + rejected AI work.

        ``rule_index_to_proposal_id`` lets us route audit entries that
        reference an original rule index to whichever ResolvedProposal
        absorbed it.
        """
        if not ai_outcome.ai_called:
            return
        del drafts  # currently only the index mapping matters

        rule_index_to_proposal_id: dict[int, int] = {}
        for r, proposal in zip(resolved, persisted_proposals, strict=True):
            if proposal.id is None:
                continue
            for rule_index in r.absorbed_rule_indices:
                rule_index_to_proposal_id[rule_index] = proposal.id

        repo = SqlSplitDecisionRepository(session)
        decisions: list[SplitDecision] = []
        for accepted in ai_outcome.accepted:
            target = accepted.target_index
            proposal_id: int | None
            if target is not None:
                proposal_id = rule_index_to_proposal_id.get(target)
            else:
                # ``add`` action: link to the AI-only proposal that was
                # persisted at the same start_page.
                proposal_id = next(
                    (
                        p.id
                        for r, p in zip(resolved, persisted_proposals, strict=True)
                        if r.source is SplitProposalSource.AI
                        and p.id is not None
                        and r.start_page == accepted.proposal.start_page
                        and r.end_page == accepted.proposal.end_page
                    ),
                    None,
                )
            if proposal_id is None:
                continue
            decisions.append(
                SplitDecision(
                    proposal_id=proposal_id,
                    actor=SplitDecisionActor.AI,
                    action=accepted.proposal.action.value,
                    payload={
                        "reason_code": accepted.proposal.reason_code,
                        "confidence": accepted.proposal.confidence,
                        "evidence_count": len(accepted.accepted_evidences),
                    },
                )
            )

        for rejected in ai_outcome.rejected:
            target = rejected.proposal.target_proposal_id
            proposal_id = rule_index_to_proposal_id.get(target) if target is not None else None
            if proposal_id is None:
                # Rejected ``add`` proposals have no SplitProposal row by
                # design (audited via JobEvent only).
                continue
            decisions.append(
                SplitDecision(
                    proposal_id=proposal_id,
                    actor=SplitDecisionActor.AI,
                    action="rejected_by_validator",
                    payload={
                        "reason_code": rejected.reason_code,
                        "ai_action": rejected.proposal.action.value,
                        "detail": rejected.detail,
                    },
                )
            )

        if decisions:
            repo.append_many(decisions)

    def _persist_parts_from_resolved(
        self,
        session: Session,
        *,
        analysis_id: int,
        resolved: tuple[ResolvedProposal, ...],
    ) -> list[DocumentPart]:
        ai_settings = self._config.settings.ai
        ai_active = ai_settings.mode is not AiMode.OFF and ai_settings.backend is not AiBackend.NONE
        if ai_active:
            auto_threshold = ai_settings.thresholds.auto_export_min_confidence
            review_below = ai_settings.thresholds.review_required_below
        else:
            auto_threshold = self._config.settings.splitter.auto_export_threshold
            review_below = auto_threshold  # below threshold → review

        parts: list[DocumentPart] = []
        for r in resolved:
            if r.rejected:
                decision = DocumentPartDecision.REVIEW_REQUIRED
            elif r.confidence >= auto_threshold:
                decision = DocumentPartDecision.AUTO_EXPORT
            elif r.confidence < review_below:
                decision = DocumentPartDecision.REVIEW_REQUIRED
            else:
                # Conservative bucket between review_below and auto_threshold.
                decision = DocumentPartDecision.REVIEW_REQUIRED
            parts.append(
                DocumentPart(
                    analysis_id=analysis_id,
                    start_page=r.start_page,
                    end_page=r.end_page,
                    decision=decision,
                    confidence=r.confidence,
                )
            )
        return list(SqlDocumentPartRepository(session).add_many(parts))

    def _export_parts(
        self,
        session: Session,
        *,
        job_id: int,
        file_original_name: str,
        resolved: tuple[ResolvedProposal, ...],
        parts: list[DocumentPart],
        split_source_path: Path,
    ) -> bool:
        """Export every AUTO_EXPORT part. Returns True iff all parts were
        auto-exported (no review required)."""
        from ..adapters.pdf import split_pdf_pages

        all_auto = True
        output_dir = Path(self._config.settings.paths.output_dir)
        work_dir = Path(self._config.settings.paths.work_dir) / "exports" / f"job-{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(file_original_name).stem
        template = self._config.settings.exporter.output_basename_template
        require_same_fs = self._config.settings.exporter.require_same_filesystem

        for index, (r, part) in enumerate(zip(resolved, parts, strict=True), start=1):
            if part.decision is not DocumentPartDecision.AUTO_EXPORT:
                all_auto = False
                continue
            if part.id is None:
                raise RuntimeError("document part was not persisted")
            self._emit_event(
                session,
                job_id,
                JobEventType.EXPORT_STARTED,
                {"part_id": part.id, "pages": [r.start_page, r.end_page]},
            )
            try:
                desired_name = template.format(stem=stem, index=index)
                work_pdf = work_dir / f"part-{index:03d}.pdf"
                split_pdf_pages(
                    split_source_path,
                    work_pdf,
                    start_page=r.start_page,
                    end_page=r.end_page,
                )
                published = atomic_publish(
                    source_path=work_pdf,
                    target_dir=output_dir,
                    desired_name=desired_name,
                    require_same_device=require_same_fs,
                )
                sha = _sha256_path(published)
                export = SqlExportRepository(session).add(
                    self._build_export_entity(
                        part_id=part.id,
                        published=published,
                        sha=sha,
                    )
                )
                if export.id is None:
                    raise RuntimeError("export was not persisted")
                SqlDocumentPartRepository(session).attach_export(part.id, export.id)
                self._emit_event(
                    session,
                    job_id,
                    JobEventType.EXPORT_COMPLETED,
                    {
                        "part_id": part.id,
                        "output_name": published.name,
                        "sha256": sha,
                    },
                )
            except Exception as exc:
                logger.exception("export failed for part %s", part.id)
                self._emit_event(
                    session,
                    job_id,
                    JobEventType.EXPORT_FAILED,
                    {"part_id": part.id, "error": str(exc)},
                )
                raise JobProcessingError("export_failed", str(exc)) from exc

        return all_auto

    def _open_review_items(
        self,
        session: Session,
        *,
        parts: list[DocumentPart],
    ) -> None:
        """Create one open ``ReviewItem`` per ``REVIEW_REQUIRED`` part."""
        repo = SqlReviewItemRepository(session)
        for part in parts:
            if part.decision is not DocumentPartDecision.REVIEW_REQUIRED:
                continue
            if part.id is None:
                raise RuntimeError("review-required part was not persisted")
            if repo.get_by_part(part.id) is not None:
                continue
            repo.add(
                ReviewItem(
                    part_id=part.id,
                    status=ReviewItemStatus.OPEN,
                )
            )

    @staticmethod
    def _build_export_entity(*, part_id: int, published: Path, sha: str) -> Any:
        from ..core.models import Export

        return Export(
            part_id=part_id,
            output_path=str(published),
            output_name=published.name,
            sha256=sha,
        )

    # -------------------------------------------------------------- helpers

    @contextmanager
    def _open_session(self) -> Any:
        session = self._config.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _emit_event(
        self,
        session: Session,
        job_id: int,
        type_: JobEventType,
        payload: dict[str, Any],
    ) -> None:
        SqlJobEventRepository(session).append(
            JobEvent(job_id=job_id, type=type_.value, payload=payload),
        )

    def _make_audit_callback(
        self,
        job_id: int,
    ) -> Callable[[str, dict[str, Any]], None]:
        """Audit callback used by the OCR adapters.

        Audit events are written in their own short transaction so they
        survive even if the surrounding processor work later rolls back.
        """
        sf = self._config.session_factory

        def cb(event_type: str, payload: dict[str, Any]) -> None:
            with sf() as s:
                SqlJobEventRepository(s).append(
                    JobEvent(job_id=job_id, type=event_type, payload=payload),
                )
                s.commit()

        return cb
