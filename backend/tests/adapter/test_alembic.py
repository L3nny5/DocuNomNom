"""Smoke test for the Alembic baseline migration."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from docunomnom.storage.db import create_engine, run_alembic_upgrade

EXPECTED_TABLES = {
    "files",
    "config_profiles",
    "keywords",
    "config_snapshots",
    "jobs",
    "job_events",
    "analysis",
    "pages",
    "split_proposals",
    "evidences",
    "split_decisions",
    "exports",
    "document_parts",
    "review_items",
    "review_markers",
}


def test_baseline_migration_creates_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "alembic.sqlite3"
    url = f"sqlite:///{db}"
    run_alembic_upgrade(url)

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


def test_partial_unique_index_exists(tmp_path: Path) -> None:
    db = tmp_path / "alembic.sqlite3"
    url = f"sqlite:///{db}"
    run_alembic_upgrade(url)
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            from sqlalchemy import text

            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).all()
        names = {r[0] for r in rows}
        assert "uq_jobs_active_run_key" in names
    finally:
        engine.dispose()
