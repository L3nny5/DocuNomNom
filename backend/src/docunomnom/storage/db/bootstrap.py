"""Schema bootstrap helpers.

Two entry points:

* :func:`run_alembic_upgrade` — used in production / docker entrypoint to
  bring the database up to ``head``.
* :func:`create_all_for_tests` — used in tests to create the schema from
  ``Base.metadata`` without running Alembic. Faster than Alembic, and the
  baseline migration is exercised separately by an Alembic-specific test.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from . import models as _models  # noqa: F401  ensure tables are registered
from .base import Base


def create_all_for_tests(engine: Engine) -> None:
    """Create all tables for the given engine. Test-only helper."""
    Base.metadata.create_all(engine)


def run_alembic_upgrade(database_url: str, *, alembic_ini: str | Path | None = None) -> None:
    """Run ``alembic upgrade head`` against ``database_url``.

    Designed to be called from the entrypoint or a small CLI; resolves the
    Alembic config relative to the backend root by default.
    """
    from alembic import command
    from alembic.config import Config

    if alembic_ini is None:
        # backend/alembic.ini, three levels up from this file:
        # src/docunomnom/storage/db/bootstrap.py -> backend/
        alembic_ini = Path(__file__).resolve().parents[4] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
