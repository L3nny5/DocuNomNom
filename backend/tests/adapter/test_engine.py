"""Tests for the SQLite engine bootstrap (PRAGMAs)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from docunomnom.storage.db import create_engine


def _pragma(engine: Engine, name: str) -> object:
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_pragmas_applied_for_file_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite3"
    engine = create_engine(f"sqlite:///{db}")
    try:
        assert _pragma(engine, "foreign_keys") == 1
        assert str(_pragma(engine, "journal_mode")).lower() == "wal"
        busy = _pragma(engine, "busy_timeout")
        assert isinstance(busy, int) and busy >= 5000
        synchronous = _pragma(engine, "synchronous")
        # NORMAL == 1
        assert synchronous == 1
    finally:
        engine.dispose()


def test_pragmas_applied_for_memory_sqlite() -> None:
    engine = create_engine("sqlite://")
    try:
        assert _pragma(engine, "foreign_keys") == 1
        busy = _pragma(engine, "busy_timeout")
        assert isinstance(busy, int) and busy >= 5000
    finally:
        engine.dispose()
