"""SQLAlchemy bootstrap, ORM models, repositories and DB-backed queue."""

from .base import Base
from .bootstrap import create_all_for_tests, run_alembic_upgrade
from .engine import (
    create_engine,
    ensure_db_directory,
    make_session_factory,
    session_scope,
)
from .queue import SqlJobQueue
from .repositories import (
    SqlAnalysisRepository,
    SqlConfigProfileRepository,
    SqlConfigSnapshotRepository,
    SqlDocumentPartRepository,
    SqlEvidenceRepository,
    SqlExportRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobRepository,
    SqlKeywordRepository,
    SqlPageRepository,
    SqlReviewItemRepository,
    SqlReviewMarkerRepository,
    SqlSplitDecisionRepository,
    SqlSplitProposalRepository,
)

__all__ = [
    "Base",
    "SqlAnalysisRepository",
    "SqlConfigProfileRepository",
    "SqlConfigSnapshotRepository",
    "SqlDocumentPartRepository",
    "SqlEvidenceRepository",
    "SqlExportRepository",
    "SqlFileRepository",
    "SqlJobEventRepository",
    "SqlJobQueue",
    "SqlJobRepository",
    "SqlKeywordRepository",
    "SqlPageRepository",
    "SqlReviewItemRepository",
    "SqlReviewMarkerRepository",
    "SqlSplitDecisionRepository",
    "SqlSplitProposalRepository",
    "create_all_for_tests",
    "create_engine",
    "ensure_db_directory",
    "make_session_factory",
    "run_alembic_upgrade",
    "session_scope",
]
