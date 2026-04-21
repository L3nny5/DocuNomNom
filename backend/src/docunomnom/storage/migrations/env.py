"""Alembic environment.

Wires Alembic into our SQLAlchemy ``Base.metadata`` and reads the database
URL from ``DOCUNOMNOM_DATABASE_URL`` if present, falling back to the value
in ``alembic.ini``. Phase 1 ships only the baseline migration.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection

from docunomnom.storage.db import create_engine

# Import models so Alembic sees the full metadata for autogenerate.
from docunomnom.storage.db import models as _models  # noqa: F401
from docunomnom.storage.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    env_url = os.environ.get("DOCUNOMNOM_DATABASE_URL")
    if env_url:
        return env_url
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("No database URL configured for Alembic")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_resolve_url())
    if engine.pool.__class__ is pool.NullPool:
        # Just to silence the unused-import warning when only NullPool is used.
        pass
    with engine.connect() as connection:
        _do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
