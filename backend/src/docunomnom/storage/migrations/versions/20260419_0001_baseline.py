"""Baseline schema (Phase 1).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-19

Creates the v1 baseline tables described in plan §5. Includes the partial
unique index that enforces "at most one active job per run_key".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_path", sa.String(2048), nullable=False),
        sa.Column("archived_path", sa.String(2048), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_files_sha256", "files", ["sha256"])

    op.create_table(
        "config_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("json_blob", sa.JSON, nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_config_profiles_hash", "config_profiles", ["hash"])

    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("config_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False, server_default="en"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
    )
    op.create_index("ix_keywords_profile_id", "keywords", ["profile_id"])

    op.create_table(
        "config_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("config_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ai_backend", sa.String(32), nullable=False),
        sa.Column("ai_mode", sa.String(32), nullable=False),
        sa.Column("ocr_backend", sa.String(32), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_config_snapshots_profile_id", "config_snapshots", ["profile_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column(
            "config_snapshot_id",
            sa.Integer,
            sa.ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_jobs_file_id", "jobs", ["file_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_run_key", "jobs", ["run_key"])
    op.create_index("ix_jobs_config_snapshot_id", "jobs", ["config_snapshot_id"])
    op.create_index("ix_jobs_status_lease_until", "jobs", ["status", "lease_until"])

    # Partial unique index: at most one active job per run_key.
    # SQLite and PostgreSQL both support this syntax.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_jobs_active_run_key
        ON jobs (run_key)
        WHERE status IN ('pending', 'processing', 'review_required')
        """
    )

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.create_table(
        "analysis",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("ocr_backend", sa.String(32), nullable=False),
        sa.Column("ai_backend", sa.String(32), nullable=False),
        sa.Column("ai_mode", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ocr_artifact_path", sa.String(2048), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id",
            sa.Integer,
            sa.ForeignKey("analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("ocr_text", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "ocr_text_truncated",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("layout_json", sa.JSON, nullable=False),
        sa.Column("hash", sa.String(64), nullable=False, server_default=""),
        sa.UniqueConstraint("analysis_id", "page_no", name="uq_pages_analysis_page"),
    )
    op.create_index("ix_pages_analysis_id", "pages", ["analysis_id"])

    op.create_table(
        "split_proposals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id",
            sa.Integer,
            sa.ForeignKey("analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("start_page", sa.Integer, nullable=False),
        sa.Column("end_page", sa.Integer, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("reason_code", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="candidate",
        ),
    )
    op.create_index("ix_split_proposals_analysis_id", "split_proposals", ["analysis_id"])

    op.create_table(
        "evidences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer,
            sa.ForeignKey("split_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_evidences_proposal_id", "evidences", ["proposal_id"])

    op.create_table(
        "split_decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer,
            sa.ForeignKey("split_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_split_decisions_proposal_id", "split_decisions", ["proposal_id"])

    op.create_table(
        "exports",
        sa.Column("id", sa.Integer, primary_key=True),
        # part_id FK is added once document_parts exists, so we declare the
        # tables in the right order: exports references parts, parts
        # back-references exports. We satisfy this with a deferred FK on
        # document_parts.export_id and a non-circular FK on exports.part_id.
        sa.Column("part_id", sa.Integer, nullable=False, unique=True),
        sa.Column("output_path", sa.String(2048), nullable=False),
        sa.Column("output_name", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_exports_sha256", "exports", ["sha256"])

    op.create_table(
        "document_parts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id",
            sa.Integer,
            sa.ForeignKey("analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_page", sa.Integer, nullable=False),
        sa.Column("end_page", sa.Integer, nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "export_id",
            sa.Integer,
            sa.ForeignKey("exports.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_document_parts_analysis_id", "document_parts", ["analysis_id"])
    op.create_index("ix_document_parts_decision", "document_parts", ["decision"])

    # Add the FK from exports.part_id -> document_parts.id now that
    # document_parts exists. Using batch-mode for SQLite portability.
    with op.batch_alter_table("exports") as batch:
        batch.create_foreign_key(
            "fk_exports_part_id_document_parts",
            "document_parts",
            ["part_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "part_id",
            sa.Integer,
            sa.ForeignKey("document_parts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="open",
        ),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_items_status", "review_items", ["status"])

    op.create_table(
        "review_markers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "review_item_id",
            sa.Integer,
            sa.ForeignKey("review_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_review_markers_review_item_id", "review_markers", ["review_item_id"])


def downgrade() -> None:
    op.drop_index("ix_review_markers_review_item_id", table_name="review_markers")
    op.drop_table("review_markers")
    op.drop_index("ix_review_items_status", table_name="review_items")
    op.drop_table("review_items")
    with op.batch_alter_table("exports") as batch:
        batch.drop_constraint("fk_exports_part_id_document_parts", type_="foreignkey")
    op.drop_index("ix_document_parts_decision", table_name="document_parts")
    op.drop_index("ix_document_parts_analysis_id", table_name="document_parts")
    op.drop_table("document_parts")
    op.drop_index("ix_exports_sha256", table_name="exports")
    op.drop_table("exports")
    op.drop_index("ix_split_decisions_proposal_id", table_name="split_decisions")
    op.drop_table("split_decisions")
    op.drop_index("ix_evidences_proposal_id", table_name="evidences")
    op.drop_table("evidences")
    op.drop_index("ix_split_proposals_analysis_id", table_name="split_proposals")
    op.drop_table("split_proposals")
    op.drop_index("ix_pages_analysis_id", table_name="pages")
    op.drop_table("pages")
    op.drop_table("analysis")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.execute("DROP INDEX IF EXISTS uq_jobs_active_run_key")
    op.drop_index("ix_jobs_status_lease_until", table_name="jobs")
    op.drop_index("ix_jobs_config_snapshot_id", table_name="jobs")
    op.drop_index("ix_jobs_run_key", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_file_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_config_snapshots_profile_id", table_name="config_snapshots")
    op.drop_table("config_snapshots")
    op.drop_index("ix_keywords_profile_id", table_name="keywords")
    op.drop_table("keywords")
    op.drop_index("ix_config_profiles_hash", table_name="config_profiles")
    op.drop_table("config_profiles")
    op.drop_index("ix_files_sha256", table_name="files")
    op.drop_table("files")
