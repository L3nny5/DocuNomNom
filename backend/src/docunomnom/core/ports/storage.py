"""Repository ports.

Concrete implementations live in ``docunomnom.storage.db.repositories``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from ..models.entities import (
    Analysis,
    ConfigProfile,
    ConfigSnapshot,
    DocumentPart,
    Evidence,
    Export,
    File,
    HistoryEntry,
    Job,
    JobEvent,
    JobSummary,
    Keyword,
    Page,
    ReviewItem,
    ReviewItemSummary,
    ReviewMarker,
    SplitDecision,
    SplitProposal,
)
from ..models.types import JobStatus, ReviewItemStatus


class FileRepositoryPort(Protocol):
    def add(self, file: File) -> File: ...
    def get(self, file_id: int) -> File | None: ...
    def find_by_sha256(self, sha256: str) -> list[File]: ...
    def set_archived_path(self, file_id: int, archived_path: str) -> File: ...


class JobRepositoryPort(Protocol):
    def add(self, job: Job) -> Job: ...
    def get(self, job_id: int) -> Job | None: ...
    def has_active_with_run_key(self, run_key: str) -> bool: ...
    def transition(
        self,
        job_id: int,
        *,
        new_status: JobStatus,
        error_code: str | None = None,
        error_msg: str | None = None,
    ) -> Job: ...
    def list_summaries(
        self,
        *,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[JobSummary], int]: ...
    def get_summary(self, job_id: int) -> JobSummary | None: ...


class JobEventRepositoryPort(Protocol):
    def append(self, event: JobEvent) -> JobEvent: ...


class ConfigSnapshotRepositoryPort(Protocol):
    def get_or_create(self, snapshot: ConfigSnapshot) -> ConfigSnapshot: ...
    def get_by_hash(self, hash_: str) -> ConfigSnapshot | None: ...


class AnalysisRepositoryPort(Protocol):
    def add(self, analysis: Analysis) -> Analysis: ...
    def get_by_job(self, job_id: int) -> Analysis | None: ...


class PageRepositoryPort(Protocol):
    def add_many(self, pages: Iterable[Page]) -> Sequence[Page]: ...
    def list_for_analysis(self, analysis_id: int) -> list[Page]: ...


class SplitProposalRepositoryPort(Protocol):
    def add_many(self, proposals: Iterable[SplitProposal]) -> Sequence[SplitProposal]: ...
    def list_for_analysis(self, analysis_id: int) -> list[SplitProposal]: ...
    def update_status(self, proposal_id: int, *, status: str) -> SplitProposal: ...


class EvidenceRepositoryPort(Protocol):
    def add_many(self, evidences: Iterable[Evidence]) -> Sequence[Evidence]: ...


class SplitDecisionRepositoryPort(Protocol):
    def append(self, decision: SplitDecision) -> SplitDecision: ...
    def append_many(self, decisions: Iterable[SplitDecision]) -> Sequence[SplitDecision]: ...
    def list_for_proposal(self, proposal_id: int) -> list[SplitDecision]: ...


class DocumentPartRepositoryPort(Protocol):
    def add_many(self, parts: Iterable[DocumentPart]) -> Sequence[DocumentPart]: ...
    def attach_export(self, part_id: int, export_id: int) -> DocumentPart: ...
    def list_for_analysis(self, analysis_id: int) -> list[DocumentPart]: ...
    def get(self, part_id: int) -> DocumentPart | None: ...
    def update_decision(
        self,
        part_id: int,
        *,
        decision: str,
    ) -> DocumentPart: ...
    def list_history(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]: ...
    def get_history_entry(self, part_id: int) -> HistoryEntry | None: ...


class ExportRepositoryPort(Protocol):
    def add(self, export: Export) -> Export: ...
    def get(self, export_id: int) -> Export | None: ...


class ConfigProfileRepositoryPort(Protocol):
    def get_by_name(self, name: str) -> ConfigProfile | None: ...
    def upsert_default(self, profile: ConfigProfile) -> ConfigProfile: ...


class KeywordRepositoryPort(Protocol):
    def list_for_profile(self, profile_id: int) -> list[Keyword]: ...
    def get(self, keyword_id: int) -> Keyword | None: ...
    def add(self, keyword: Keyword) -> Keyword: ...
    def update(self, keyword: Keyword) -> Keyword: ...
    def delete(self, keyword_id: int) -> bool: ...


class ReviewItemRepositoryPort(Protocol):
    def add(self, item: ReviewItem) -> ReviewItem: ...
    def get(self, item_id: int) -> ReviewItem | None: ...
    def get_by_part(self, part_id: int) -> ReviewItem | None: ...
    def get_summary(self, item_id: int) -> ReviewItemSummary | None: ...
    def list_summaries(
        self,
        *,
        status: ReviewItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReviewItemSummary], int]: ...
    def transition(
        self,
        item_id: int,
        *,
        new_status: ReviewItemStatus,
        finished_at: datetime | None = None,
        reviewer_notes: str | None = None,
    ) -> ReviewItem: ...
    def count_open_for_analysis(self, analysis_id: int) -> int: ...


class ReviewMarkerRepositoryPort(Protocol):
    def list_for_item(self, item_id: int) -> list[ReviewMarker]: ...
    def replace_for_item(
        self,
        item_id: int,
        markers: Iterable[ReviewMarker],
    ) -> list[ReviewMarker]: ...
