"""SQLite engine bootstrap.

Implements the v1 invariants from plan §3:

- ``journal_mode=WAL``        — concurrent reads while one writer is active.
- ``busy_timeout=5000`` ms     — give writers a chance instead of failing fast.
- ``synchronous=NORMAL``       — safe with WAL.
- ``foreign_keys=ON``          — enforce ON DELETE / RESTRICT.

The PRAGMAs are applied via a ``connect`` event so they are set on every
new connection in the pool, not just on the first one.

The single-worker invariant is *not* enforced here — it is documented as a
deployment constraint and verified by the entrypoint and the worker startup
banner.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine as _create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_BUSY_TIMEOUT_MS = 5000


def _is_sqlite_url(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def _is_in_memory_sqlite(url: str) -> bool:
    if not _is_sqlite_url(url):
        return False
    sa_url = make_url(url)
    db = sa_url.database or ""
    # Both ``:memory:`` and the empty database are in-memory.
    return db in ("", ":memory:") or db.startswith("file::memory:")


def _apply_sqlite_pragmas(
    dbapi_connection: DBAPIConnection,
    _connection_record: Any,
) -> None:
    """Apply the v1 PRAGMAs on every new SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
        # WAL is a no-op for ``:memory:`` databases; SQLite silently keeps
        # ``journal_mode=memory`` in that case, which is fine for tests.
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def create_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy ``Engine`` configured for the v1 SQLite setup.

    For ``sqlite://`` (in-memory) we also disable connection pooling so the
    same connection backs every checkout — otherwise every test would see an
    empty database.
    """
    if _is_in_memory_sqlite(url):
        from sqlalchemy.pool import StaticPool

        engine = _create_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    else:
        engine = _create_engine(
            url,
            echo=echo,
            future=True,
        )

    if _is_sqlite_url(url):
        event.listen(engine, "connect", _apply_sqlite_pragmas)

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Short-lived transactional session.

    The caller's transaction commits on success and rolls back on failure.
    Heavy CPU/IO work (OCR, AI, export) must NOT be done inside this scope
    so SQLite write contention stays low (plan §3).
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_db_directory(sqlite_path: Path) -> None:
    """Create the parent directory of a SQLite file if it does not exist."""
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
