"""SQLAlchemy-backed repository implementations.

Each repository implements a port declared in ``docunomnom.core.ports.storage``
and translates between domain entities and ORM rows. Repositories are
session-scoped: callers pass an open ``Session`` to the constructor.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.models import (
    ACTIVE_JOB_STATUSES,
    AiBackend,
    AiMode,
    Analysis,
    ConfigProfile,
    ConfigSnapshot,
    DocumentPart,
    DocumentPartDecision,
    Evidence,
    EvidenceKind,
    Export,
    File,
    HistoryEntry,
    Job,
    JobEvent,
    JobStatus,
    JobSummary,
    Keyword,
    OcrBackend,
    Page,
    ReviewItem,
    ReviewItemStatus,
    ReviewItemSummary,
    ReviewMarker,
    ReviewMarkerKind,
    SplitDecision,
    SplitDecisionActor,
    SplitProposal,
    SplitProposalSource,
    SplitProposalStatus,
)
from ...core.usecases.transition_job import ensure_transition_allowed
from .models import (
    AnalysisORM,
    ConfigProfileORM,
    ConfigSnapshotORM,
    DocumentPartORM,
    EvidenceORM,
    ExportORM,
    FileORM,
    JobEventORM,
    JobORM,
    KeywordORM,
    PageORM,
    ReviewItemORM,
    ReviewMarkerORM,
    SplitDecisionORM,
    SplitProposalORM,
)


def _to_file(row: FileORM) -> File:
    return File(
        id=row.id,
        sha256=row.sha256,
        original_name=row.original_name,
        size=row.size,
        mtime=row.mtime,
        source_path=row.source_path,
        archived_path=row.archived_path,
        created_at=row.created_at,
    )


def _to_job(row: JobORM) -> Job:
    return Job(
        id=row.id,
        file_id=row.file_id,
        status=JobStatus(row.status),
        mode=AiMode(row.mode),
        attempt=row.attempt,
        lease_until=row.lease_until,
        error_code=row.error_code,
        error_msg=row.error_msg,
        run_key=row.run_key,
        config_snapshot_id=row.config_snapshot_id,
        pipeline_version=row.pipeline_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_snapshot(row: ConfigSnapshotORM) -> ConfigSnapshot:
    return ConfigSnapshot(
        id=row.id,
        profile_id=row.profile_id,
        hash=row.hash,
        ai_backend=AiBackend(row.ai_backend),
        ai_mode=AiMode(row.ai_mode),
        ocr_backend=OcrBackend(row.ocr_backend),
        pipeline_version=row.pipeline_version,
        payload=dict(row.payload),
        created_at=row.created_at,
    )


def _to_event(row: JobEventORM) -> JobEvent:
    return JobEvent(
        id=row.id,
        job_id=row.job_id,
        ts=row.ts,
        type=row.type,
        payload=dict(row.payload),
    )


def _to_analysis(row: AnalysisORM) -> Analysis:
    return Analysis(
        id=row.id,
        job_id=row.job_id,
        ocr_backend=OcrBackend(row.ocr_backend),
        ai_backend=AiBackend(row.ai_backend),
        ai_mode=AiMode(row.ai_mode),
        page_count=row.page_count,
        ocr_artifact_path=row.ocr_artifact_path,
        created_at=row.created_at,
    )


def _to_page(row: PageORM) -> Page:
    return Page(
        id=row.id,
        analysis_id=row.analysis_id,
        page_no=row.page_no,
        text=row.ocr_text,
        text_truncated=row.ocr_text_truncated,
        layout=dict(row.layout_json),
        hash=row.hash,
    )


def _to_proposal(row: SplitProposalORM) -> SplitProposal:
    return SplitProposal(
        id=row.id,
        analysis_id=row.analysis_id,
        source=SplitProposalSource(row.source),
        start_page=row.start_page,
        end_page=row.end_page,
        confidence=row.confidence,
        reason_code=row.reason_code,
        status=SplitProposalStatus(row.status),
    )


def _to_part(row: DocumentPartORM) -> DocumentPart:
    return DocumentPart(
        id=row.id,
        analysis_id=row.analysis_id,
        start_page=row.start_page,
        end_page=row.end_page,
        decision=DocumentPartDecision(row.decision),
        confidence=row.confidence,
        export_id=row.export_id,
    )


def _to_export(row: ExportORM) -> Export:
    return Export(
        id=row.id,
        part_id=row.part_id,
        output_path=row.output_path,
        output_name=row.output_name,
        sha256=row.sha256,
        exported_at=row.exported_at,
    )


def _to_keyword(row: KeywordORM) -> Keyword:
    return Keyword(
        id=row.id,
        profile_id=row.profile_id,
        term=row.term,
        locale=row.locale,
        enabled=row.enabled,
        weight=row.weight,
    )


def _to_profile(row: ConfigProfileORM) -> ConfigProfile:
    return ConfigProfile(
        id=row.id,
        name=row.name,
        json_blob=dict(row.json_blob),
        hash=row.hash,
    )


def _to_review_item(row: ReviewItemORM) -> ReviewItem:
    return ReviewItem(
        id=row.id,
        part_id=row.part_id,
        status=ReviewItemStatus(row.status),
        reviewer_notes=row.reviewer_notes,
        finished_at=row.finished_at,
    )


def _to_review_marker(row: ReviewMarkerORM) -> ReviewMarker:
    return ReviewMarker(
        id=row.id,
        review_item_id=row.review_item_id,
        page_no=row.page_no,
        kind=ReviewMarkerKind(row.kind),
        ts=row.ts,
    )


def _to_evidence(row: EvidenceORM) -> Evidence:
    return Evidence(
        id=row.id,
        proposal_id=row.proposal_id,
        kind=EvidenceKind(row.kind),
        page_no=row.page_no,
        snippet=row.snippet,
        payload=dict(row.payload),
    )


def _to_split_decision(row: SplitDecisionORM) -> SplitDecision:
    return SplitDecision(
        id=row.id,
        proposal_id=row.proposal_id,
        actor=SplitDecisionActor(row.actor),
        action=row.action,
        ts=row.ts,
        payload=dict(row.payload),
    )


class SqlFileRepository:
    """``FileRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, file: File) -> File:
        row = FileORM(
            sha256=file.sha256,
            original_name=file.original_name,
            size=file.size,
            mtime=file.mtime,
            source_path=file.source_path,
            archived_path=file.archived_path,
        )
        self._session.add(row)
        self._session.flush()
        return _to_file(row)

    def get(self, file_id: int) -> File | None:
        row = self._session.get(FileORM, file_id)
        return _to_file(row) if row else None

    def find_by_sha256(self, sha256: str) -> list[File]:
        stmt = select(FileORM).where(FileORM.sha256 == sha256).order_by(FileORM.id.asc())
        return [_to_file(r) for r in self._session.scalars(stmt).all()]

    def set_archived_path(self, file_id: int, archived_path: str) -> File:
        row = self._session.get(FileORM, file_id)
        if row is None:
            raise LookupError(f"File {file_id} not found")
        row.archived_path = archived_path
        self._session.flush()
        return _to_file(row)


class SqlConfigSnapshotRepository:
    """``ConfigSnapshotRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_hash(self, hash_: str) -> ConfigSnapshot | None:
        stmt = select(ConfigSnapshotORM).where(ConfigSnapshotORM.hash == hash_)
        row = self._session.scalars(stmt).one_or_none()
        return _to_snapshot(row) if row else None

    def get_or_create(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        existing = self.get_by_hash(snapshot.hash)
        if existing is not None:
            return existing
        row = ConfigSnapshotORM(
            profile_id=snapshot.profile_id,
            hash=snapshot.hash,
            ai_backend=snapshot.ai_backend.value,
            ai_mode=snapshot.ai_mode.value,
            ocr_backend=snapshot.ocr_backend.value,
            pipeline_version=snapshot.pipeline_version,
            payload=dict(snapshot.payload),
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError:
            # Lost a race with another session that just inserted the same
            # snapshot. Re-read and return the existing one.
            self._session.rollback()
            existing = self.get_by_hash(snapshot.hash)
            if existing is None:
                raise
            return existing
        return _to_snapshot(row)


class SqlJobRepository:
    """``JobRepositoryPort`` implementation.

    Status transitions go through :func:`ensure_transition_allowed` so the
    state machine cannot be bypassed.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: Job) -> Job:
        row = JobORM(
            file_id=job.file_id,
            status=job.status.value,
            mode=job.mode.value,
            attempt=job.attempt,
            lease_until=job.lease_until,
            error_code=job.error_code,
            error_msg=job.error_msg,
            run_key=job.run_key,
            config_snapshot_id=job.config_snapshot_id,
            pipeline_version=job.pipeline_version,
        )
        self._session.add(row)
        self._session.flush()
        return _to_job(row)

    def get(self, job_id: int) -> Job | None:
        row = self._session.get(JobORM, job_id)
        return _to_job(row) if row else None

    def has_active_with_run_key(self, run_key: str) -> bool:
        stmt = (
            select(JobORM.id)
            .where(JobORM.run_key == run_key)
            .where(JobORM.status.in_([s.value for s in ACTIVE_JOB_STATUSES]))
            .limit(1)
        )
        return self._session.scalars(stmt).first() is not None

    def transition(
        self,
        job_id: int,
        *,
        new_status: JobStatus,
        error_code: str | None = None,
        error_msg: str | None = None,
    ) -> Job:
        row = self._session.get(JobORM, job_id)
        if row is None:
            raise LookupError(f"Job {job_id} not found")
        ensure_transition_allowed(JobStatus(row.status), new_status)
        row.status = new_status.value
        # Clear retry-related fields on entry to terminal-friendly states.
        if new_status is JobStatus.PENDING:
            row.lease_until = None
            row.error_code = None
            row.error_msg = None
        if error_code is not None:
            row.error_code = error_code
        if error_msg is not None:
            row.error_msg = error_msg
        self._session.flush()
        return _to_job(row)

    def list_summaries(
        self,
        *,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[JobSummary], int]:
        base = select(JobORM, FileORM).join(FileORM, JobORM.file_id == FileORM.id)
        count_stmt = select(func.count()).select_from(JobORM)
        if status is not None:
            base = base.where(JobORM.status == status.value)
            count_stmt = count_stmt.where(JobORM.status == status.value)
        base = base.order_by(JobORM.created_at.desc(), JobORM.id.desc())
        base = base.limit(max(1, min(limit, 500))).offset(max(0, offset))

        total = int(self._session.scalar(count_stmt) or 0)
        rows = self._session.execute(base).all()
        summaries = [
            JobSummary(
                id=int(job.id),
                file_id=int(file.id),
                file_name=file.original_name,
                file_sha256=file.sha256,
                status=JobStatus(job.status),
                mode=AiMode(job.mode),
                attempt=job.attempt,
                pipeline_version=job.pipeline_version,
                created_at=job.created_at,
                updated_at=job.updated_at,
                error_code=job.error_code,
                error_msg=job.error_msg,
            )
            for job, file in rows
        ]
        return summaries, total

    def get_summary(self, job_id: int) -> JobSummary | None:
        stmt = (
            select(JobORM, FileORM)
            .join(FileORM, JobORM.file_id == FileORM.id)
            .where(JobORM.id == job_id)
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        job, file = row
        return JobSummary(
            id=int(job.id),
            file_id=int(file.id),
            file_name=file.original_name,
            file_sha256=file.sha256,
            status=JobStatus(job.status),
            mode=AiMode(job.mode),
            attempt=job.attempt,
            pipeline_version=job.pipeline_version,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_code=job.error_code,
            error_msg=job.error_msg,
        )


class SqlJobEventRepository:
    """``JobEventRepositoryPort`` implementation. Append-only by contract."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: JobEvent) -> JobEvent:
        row = JobEventORM(
            job_id=event.job_id,
            type=event.type,
            payload=dict(event.payload),
        )
        self._session.add(row)
        self._session.flush()
        return _to_event(row)


class SqlAnalysisRepository:
    """``AnalysisRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, analysis: Analysis) -> Analysis:
        row = AnalysisORM(
            job_id=analysis.job_id,
            ocr_backend=analysis.ocr_backend.value,
            ai_backend=analysis.ai_backend.value,
            ai_mode=analysis.ai_mode.value,
            page_count=analysis.page_count,
            ocr_artifact_path=analysis.ocr_artifact_path,
        )
        self._session.add(row)
        self._session.flush()
        return _to_analysis(row)

    def get_by_job(self, job_id: int) -> Analysis | None:
        stmt = select(AnalysisORM).where(AnalysisORM.job_id == job_id)
        row = self._session.scalars(stmt).one_or_none()
        return _to_analysis(row) if row else None


class SqlPageRepository:
    """``PageRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, pages: Iterable[Page]) -> Sequence[Page]:
        rows = [
            PageORM(
                analysis_id=p.analysis_id,
                page_no=p.page_no,
                ocr_text=p.text,
                ocr_text_truncated=p.text_truncated,
                layout_json=dict(p.layout),
                hash=p.hash,
            )
            for p in pages
        ]
        self._session.add_all(rows)
        self._session.flush()
        return [_to_page(r) for r in rows]

    def list_for_analysis(self, analysis_id: int) -> list[Page]:
        stmt = (
            select(PageORM)
            .where(PageORM.analysis_id == analysis_id)
            .order_by(PageORM.page_no.asc())
        )
        return [_to_page(r) for r in self._session.scalars(stmt).all()]


class SqlSplitProposalRepository:
    """``SplitProposalRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, proposals: Iterable[SplitProposal]) -> Sequence[SplitProposal]:
        rows = [
            SplitProposalORM(
                analysis_id=p.analysis_id,
                source=p.source.value,
                start_page=p.start_page,
                end_page=p.end_page,
                confidence=p.confidence,
                reason_code=p.reason_code,
                status=p.status.value,
            )
            for p in proposals
        ]
        self._session.add_all(rows)
        self._session.flush()
        return [_to_proposal(r) for r in rows]

    def list_for_analysis(self, analysis_id: int) -> list[SplitProposal]:
        stmt = (
            select(SplitProposalORM)
            .where(SplitProposalORM.analysis_id == analysis_id)
            .order_by(SplitProposalORM.start_page.asc(), SplitProposalORM.id.asc())
        )
        return [_to_proposal(r) for r in self._session.scalars(stmt).all()]

    def update_status(self, proposal_id: int, *, status: str) -> SplitProposal:
        row = self._session.get(SplitProposalORM, proposal_id)
        if row is None:
            raise LookupError(f"SplitProposal {proposal_id} not found")
        row.status = status
        self._session.flush()
        return _to_proposal(row)


class SqlSplitDecisionRepository:
    """``SplitDecisionRepositoryPort`` implementation. Append-only audit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, decision: SplitDecision) -> SplitDecision:
        row = SplitDecisionORM(
            proposal_id=decision.proposal_id,
            actor=decision.actor.value,
            action=decision.action,
            payload=dict(decision.payload),
        )
        self._session.add(row)
        self._session.flush()
        return _to_split_decision(row)

    def append_many(self, decisions: Iterable[SplitDecision]) -> Sequence[SplitDecision]:
        rows = [
            SplitDecisionORM(
                proposal_id=d.proposal_id,
                actor=d.actor.value,
                action=d.action,
                payload=dict(d.payload),
            )
            for d in decisions
        ]
        self._session.add_all(rows)
        self._session.flush()
        return [_to_split_decision(r) for r in rows]

    def list_for_proposal(self, proposal_id: int) -> list[SplitDecision]:
        stmt = (
            select(SplitDecisionORM)
            .where(SplitDecisionORM.proposal_id == proposal_id)
            .order_by(SplitDecisionORM.id.asc())
        )
        return [_to_split_decision(r) for r in self._session.scalars(stmt).all()]


class SqlEvidenceRepository:
    """``EvidenceRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, evidences: Iterable[Evidence]) -> Sequence[Evidence]:
        rows = [
            EvidenceORM(
                proposal_id=e.proposal_id,
                kind=e.kind.value,
                page_no=e.page_no,
                snippet=e.snippet,
                payload=dict(e.payload),
            )
            for e in evidences
        ]
        self._session.add_all(rows)
        self._session.flush()
        return [_to_evidence(r) for r in rows]


class SqlDocumentPartRepository:
    """``DocumentPartRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, parts: Iterable[DocumentPart]) -> Sequence[DocumentPart]:
        rows = [
            DocumentPartORM(
                analysis_id=p.analysis_id,
                start_page=p.start_page,
                end_page=p.end_page,
                decision=p.decision.value,
                confidence=p.confidence,
                export_id=p.export_id,
            )
            for p in parts
        ]
        self._session.add_all(rows)
        self._session.flush()
        return [_to_part(r) for r in rows]

    def attach_export(self, part_id: int, export_id: int) -> DocumentPart:
        row = self._session.get(DocumentPartORM, part_id)
        if row is None:
            raise LookupError(f"DocumentPart {part_id} not found")
        row.export_id = export_id
        self._session.flush()
        return _to_part(row)

    def list_for_analysis(self, analysis_id: int) -> list[DocumentPart]:
        stmt = (
            select(DocumentPartORM)
            .where(DocumentPartORM.analysis_id == analysis_id)
            .order_by(DocumentPartORM.start_page.asc(), DocumentPartORM.id.asc())
        )
        return [_to_part(r) for r in self._session.scalars(stmt).all()]

    def get(self, part_id: int) -> DocumentPart | None:
        row = self._session.get(DocumentPartORM, part_id)
        return _to_part(row) if row else None

    def update_decision(self, part_id: int, *, decision: str) -> DocumentPart:
        row = self._session.get(DocumentPartORM, part_id)
        if row is None:
            raise LookupError(f"DocumentPart {part_id} not found")
        row.decision = decision
        self._session.flush()
        return _to_part(row)

    def list_history(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        # History = parts that have been exported (export attached). The join
        # walks part -> analysis -> job -> file so the response carries
        # operator-friendly file metadata.
        base = (
            select(DocumentPartORM, AnalysisORM, JobORM, FileORM, ExportORM)
            .join(AnalysisORM, DocumentPartORM.analysis_id == AnalysisORM.id)
            .join(JobORM, AnalysisORM.job_id == JobORM.id)
            .join(FileORM, JobORM.file_id == FileORM.id)
            .join(ExportORM, ExportORM.part_id == DocumentPartORM.id)
            .order_by(ExportORM.exported_at.desc(), DocumentPartORM.id.desc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        count_stmt = (
            select(func.count())
            .select_from(DocumentPartORM)
            .join(ExportORM, ExportORM.part_id == DocumentPartORM.id)
        )
        total = int(self._session.scalar(count_stmt) or 0)
        rows = self._session.execute(base).all()
        entries = [
            HistoryEntry(
                part_id=int(part.id),
                job_id=int(job.id),
                file_id=int(file.id),
                file_name=file.original_name,
                start_page=part.start_page,
                end_page=part.end_page,
                decision=DocumentPartDecision(part.decision),
                confidence=part.confidence,
                output_name=export.output_name,
                output_path=export.output_path,
                sha256=export.sha256,
                exported_at=export.exported_at,
            )
            for part, _analysis, job, file, export in rows
        ]
        return entries, total

    def get_history_entry(self, part_id: int) -> HistoryEntry | None:
        stmt = (
            select(DocumentPartORM, AnalysisORM, JobORM, FileORM, ExportORM)
            .join(AnalysisORM, DocumentPartORM.analysis_id == AnalysisORM.id)
            .join(JobORM, AnalysisORM.job_id == JobORM.id)
            .join(FileORM, JobORM.file_id == FileORM.id)
            .join(ExportORM, ExportORM.part_id == DocumentPartORM.id)
            .where(DocumentPartORM.id == part_id)
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        part, _analysis, job, file, export = row
        return HistoryEntry(
            part_id=int(part.id),
            job_id=int(job.id),
            file_id=int(file.id),
            file_name=file.original_name,
            start_page=part.start_page,
            end_page=part.end_page,
            decision=DocumentPartDecision(part.decision),
            confidence=part.confidence,
            output_name=export.output_name,
            output_path=export.output_path,
            sha256=export.sha256,
            exported_at=export.exported_at,
        )


class SqlExportRepository:
    """``ExportRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, export: Export) -> Export:
        row = ExportORM(
            part_id=export.part_id,
            output_path=export.output_path,
            output_name=export.output_name,
            sha256=export.sha256,
        )
        self._session.add(row)
        self._session.flush()
        return _to_export(row)

    def get(self, export_id: int) -> Export | None:
        row = self._session.get(ExportORM, export_id)
        return _to_export(row) if row else None


class SqlConfigProfileRepository:
    """``ConfigProfileRepositoryPort`` implementation.

    v1 only ever materializes a single profile (``DEFAULT_PROFILE_NAME``);
    ``upsert_default`` creates it if missing and otherwise replaces its
    ``json_blob`` and ``hash`` in place.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_name(self, name: str) -> ConfigProfile | None:
        stmt = select(ConfigProfileORM).where(ConfigProfileORM.name == name)
        row = self._session.scalars(stmt).one_or_none()
        return _to_profile(row) if row else None

    def upsert_default(self, profile: ConfigProfile) -> ConfigProfile:
        stmt = select(ConfigProfileORM).where(ConfigProfileORM.name == profile.name)
        row = self._session.scalars(stmt).one_or_none()
        if row is None:
            row = ConfigProfileORM(
                name=profile.name,
                json_blob=dict(profile.json_blob),
                hash=profile.hash,
            )
            self._session.add(row)
        else:
            row.json_blob = dict(profile.json_blob)
            row.hash = profile.hash
        self._session.flush()
        return _to_profile(row)


class SqlKeywordRepository:
    """``KeywordRepositoryPort`` implementation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_profile(self, profile_id: int) -> list[Keyword]:
        stmt = (
            select(KeywordORM)
            .where(KeywordORM.profile_id == profile_id)
            .order_by(KeywordORM.term.asc(), KeywordORM.id.asc())
        )
        return [_to_keyword(r) for r in self._session.scalars(stmt).all()]

    def get(self, keyword_id: int) -> Keyword | None:
        row = self._session.get(KeywordORM, keyword_id)
        return _to_keyword(row) if row else None

    def add(self, keyword: Keyword) -> Keyword:
        row = KeywordORM(
            profile_id=keyword.profile_id,
            term=keyword.term,
            locale=keyword.locale,
            enabled=keyword.enabled,
            weight=keyword.weight,
        )
        self._session.add(row)
        self._session.flush()
        return _to_keyword(row)

    def update(self, keyword: Keyword) -> Keyword:
        if keyword.id is None:
            raise ValueError("keyword.id required for update")
        row = self._session.get(KeywordORM, keyword.id)
        if row is None:
            raise LookupError(f"Keyword {keyword.id} not found")
        row.term = keyword.term
        row.locale = keyword.locale
        row.enabled = keyword.enabled
        row.weight = keyword.weight
        self._session.flush()
        return _to_keyword(row)

    def delete(self, keyword_id: int) -> bool:
        row = self._session.get(KeywordORM, keyword_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


def _summary_from_join(
    item: ReviewItemORM,
    part: DocumentPartORM,
    analysis: AnalysisORM,
    job: JobORM,
    file: FileORM,
) -> ReviewItemSummary:
    return ReviewItemSummary(
        id=int(item.id),
        part_id=int(part.id),
        status=ReviewItemStatus(item.status),
        job_id=int(job.id),
        analysis_id=int(analysis.id),
        file_id=int(file.id),
        file_name=file.original_name,
        start_page=part.start_page,
        end_page=part.end_page,
        confidence=part.confidence,
        decision=DocumentPartDecision(part.decision),
        page_count=analysis.page_count,
        finished_at=item.finished_at,
    )


class SqlReviewItemRepository:
    """``ReviewItemRepositoryPort`` implementation.

    All listings join part -> analysis -> job -> file so the API can ship
    enough context for the review UI to render without a follow-up call.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: ReviewItem) -> ReviewItem:
        row = ReviewItemORM(
            part_id=item.part_id,
            status=item.status.value,
            reviewer_notes=item.reviewer_notes,
            finished_at=item.finished_at,
        )
        self._session.add(row)
        self._session.flush()
        return _to_review_item(row)

    def get(self, item_id: int) -> ReviewItem | None:
        row = self._session.get(ReviewItemORM, item_id)
        return _to_review_item(row) if row else None

    def get_by_part(self, part_id: int) -> ReviewItem | None:
        stmt = select(ReviewItemORM).where(ReviewItemORM.part_id == part_id)
        row = self._session.scalars(stmt).one_or_none()
        return _to_review_item(row) if row else None

    def _summary_select(self) -> Any:
        return (
            select(ReviewItemORM, DocumentPartORM, AnalysisORM, JobORM, FileORM)
            .join(DocumentPartORM, ReviewItemORM.part_id == DocumentPartORM.id)
            .join(AnalysisORM, DocumentPartORM.analysis_id == AnalysisORM.id)
            .join(JobORM, AnalysisORM.job_id == JobORM.id)
            .join(FileORM, JobORM.file_id == FileORM.id)
        )

    def get_summary(self, item_id: int) -> ReviewItemSummary | None:
        stmt = self._summary_select().where(ReviewItemORM.id == item_id)
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        return _summary_from_join(*row)

    def list_summaries(
        self,
        *,
        status: ReviewItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReviewItemSummary], int]:
        base = self._summary_select()
        count_stmt = select(func.count()).select_from(ReviewItemORM)
        if status is not None:
            base = base.where(ReviewItemORM.status == status.value)
            count_stmt = count_stmt.where(ReviewItemORM.status == status.value)
        base = (
            base.order_by(ReviewItemORM.id.desc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        total = int(self._session.scalar(count_stmt) or 0)
        rows = self._session.execute(base).all()
        items = [_summary_from_join(*row) for row in rows]
        return items, total

    def transition(
        self,
        item_id: int,
        *,
        new_status: ReviewItemStatus,
        finished_at: datetime | None = None,
        reviewer_notes: str | None = None,
    ) -> ReviewItem:
        row = self._session.get(ReviewItemORM, item_id)
        if row is None:
            raise LookupError(f"ReviewItem {item_id} not found")
        row.status = new_status.value
        if finished_at is not None:
            row.finished_at = finished_at
        if reviewer_notes is not None:
            row.reviewer_notes = reviewer_notes
        self._session.flush()
        return _to_review_item(row)

    def count_open_for_analysis(self, analysis_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(ReviewItemORM)
            .join(DocumentPartORM, ReviewItemORM.part_id == DocumentPartORM.id)
            .where(DocumentPartORM.analysis_id == analysis_id)
            .where(ReviewItemORM.status != ReviewItemStatus.DONE.value)
        )
        return int(self._session.scalar(stmt) or 0)


class SqlReviewMarkerRepository:
    """``ReviewMarkerRepositoryPort`` implementation.

    Markers belong to a single review item; replacement is total (delete
    all then insert) to mirror the PUT semantics of the API endpoint.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_item(self, item_id: int) -> list[ReviewMarker]:
        stmt = (
            select(ReviewMarkerORM)
            .where(ReviewMarkerORM.review_item_id == item_id)
            .order_by(ReviewMarkerORM.page_no.asc(), ReviewMarkerORM.id.asc())
        )
        return [_to_review_marker(r) for r in self._session.scalars(stmt).all()]

    def replace_for_item(
        self,
        item_id: int,
        markers: Iterable[ReviewMarker],
    ) -> list[ReviewMarker]:
        existing = self._session.scalars(
            select(ReviewMarkerORM).where(ReviewMarkerORM.review_item_id == item_id)
        ).all()
        for row in existing:
            self._session.delete(row)
        self._session.flush()
        new_rows = [
            ReviewMarkerORM(
                review_item_id=item_id,
                page_no=m.page_no,
                kind=m.kind.value,
            )
            for m in markers
        ]
        self._session.add_all(new_rows)
        self._session.flush()
        return [_to_review_marker(r) for r in new_rows]
