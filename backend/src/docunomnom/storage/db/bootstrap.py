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


def _packaged_migrations_dir() -> Path:
    """Resolve the directory that ships the Alembic ``env.py`` and
    ``versions/`` tree.

    The migrations tree is force-included into the wheel via
    ``pyproject.toml`` (``[tool.hatch.build.targets.wheel.force-include]``),
    so it lives next to the ``docunomnom.storage`` package both in an
    installed context (``site-packages/docunomnom/storage/migrations``)
    and in a source checkout (``backend/src/docunomnom/storage/migrations``).
    """
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    if not (migrations_dir / "env.py").is_file():
        raise RuntimeError(
            f"Alembic migrations directory is missing or incomplete at "
            f"{migrations_dir}; the package build is broken. "
            "Expected env.py alongside versions/."
        )
    return migrations_dir


def run_alembic_upgrade(database_url: str, *, alembic_ini: str | Path | None = None) -> None:
    """Run ``alembic upgrade head`` against ``database_url``.

    Two supported modes:

    * ``alembic_ini is None`` (the production / installed-package path):
      build an ``alembic.config.Config`` purely in memory, pointing
      ``script_location`` at the migrations directory shipped inside the
      ``docunomnom`` package. This is what the Docker worker uses and it
      does NOT require an external ``alembic.ini`` file on disk — the
      image only needs the installed wheel.

    * ``alembic_ini`` given (developer / CI convenience): load that file
      as usual. This preserves ``backend/alembic.ini`` for the ``alembic``
      CLI workflow (autogenerate, history, etc.).

    In both modes ``sqlalchemy.url`` is overridden with ``database_url``
    so the env override resolved by :mod:`docunomnom.config.settings`
    always wins over any static value inside an ini file.
    """
    from alembic import command
    from alembic.config import Config

    if alembic_ini is not None:
        cfg = Config(str(alembic_ini))
    else:
        # File-less config: Alembic accepts a Config() with no ini file
        # as long as script_location is set programmatically.
        cfg = Config()
        cfg.set_main_option("script_location", str(_packaged_migrations_dir()))

    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
