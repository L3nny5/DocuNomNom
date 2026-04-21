"""SQLAlchemy ORM models for the v1 baseline schema (plan §5).

All Phase 1 models are declared here so Alembic can autogenerate against
them and so the schema stays in one place. Phase 1 only actively uses
``files``, ``jobs``, ``job_events``, ``config_profiles``, ``keywords``, and
``config_snapshots`` from code; the remaining tables are scaffolded so the
schema is locked early and so later phases plug in without breaking
migrations.

Type choices are intentionally portable to PostgreSQL (no SQLite-only
features). JSON columns use SQLAlchemy ``JSON`` which maps to TEXT on
SQLite and JSONB on PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FileORM(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    archived_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    jobs: Mapped[list[JobORM]] = relationship(back_populates="file")


class ConfigProfileORM(Base):
    __tablename__ = "config_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    json_blob: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class KeywordORM(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class ConfigSnapshotORM(Base):
    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("config_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ai_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobORM(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    config_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    file: Mapped[FileORM] = relationship(back_populates="jobs")
    events: Mapped[list[JobEventORM]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_jobs_status_lease_until", "status", "lease_until"),
        # The partial unique index that enforces "at most one active job per
        # run_key" lives in the migration as raw SQL because Alembic+SQLite
        # need an explicit WHERE clause that DeclarativeBase cannot express
        # in a portable way.
    )


class JobEventORM(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    job: Mapped[JobORM] = relationship(back_populates="events")


class AnalysisORM(Base):
    __tablename__ = "analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    ocr_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_artifact_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PageORM(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ocr_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ocr_text_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    layout_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    __table_args__ = (UniqueConstraint("analysis_id", "page_no", name="uq_pages_analysis_page"),)


class SplitProposalORM(Base):
    __tablename__ = "split_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")


class EvidenceORM(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("split_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class SplitDecisionORM(Base):
    __tablename__ = "split_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("split_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DocumentPartORM(Base):
    __tablename__ = "document_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    export_id: Mapped[int | None] = mapped_column(
        ForeignKey("exports.id", ondelete="SET NULL"), nullable=True
    )


class ExportORM(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("document_parts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    output_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    output_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewItemORM(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("document_parts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewMarkerORM(Base):
    __tablename__ = "review_markers"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_item_id: Mapped[int] = mapped_column(
        ForeignKey("review_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "AnalysisORM",
    "Base",
    "ConfigProfileORM",
    "ConfigSnapshotORM",
    "DocumentPartORM",
    "EvidenceORM",
    "ExportORM",
    "FileORM",
    "JobEventORM",
    "JobORM",
    "KeywordORM",
    "PageORM",
    "ReviewItemORM",
    "ReviewMarkerORM",
    "SplitDecisionORM",
    "SplitProposalORM",
]
