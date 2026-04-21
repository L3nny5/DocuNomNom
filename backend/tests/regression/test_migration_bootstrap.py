"""Regression: Alembic bootstrap must work in an installed-package
context with no external ``alembic.ini`` on disk.

Background: the Docker image installs the wheel into site-packages and
does not ship ``backend/alembic.ini``. A previous implementation of
``run_alembic_upgrade`` resolved the ini path with ``Path(__file__).parents[4]``,
which points at ``site-packages/python3.12/`` in a real container,
causing::

    alembic.util.exc.CommandError: No 'script_location' key found in configuration.

This test asserts that the installed-package code path (``alembic_ini=None``)
applies the baseline migration without needing any file on disk.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import docunomnom.storage.migrations as _packaged_migrations
from docunomnom.storage.db.bootstrap import run_alembic_upgrade


def test_migration_runs_without_external_alembic_ini(tmp_path: Path, monkeypatch) -> None:
    """Running migrations from an installed package must not depend on
    ``backend/alembic.ini`` being present at runtime."""
    # Simulate the container: CWD far away from the repo, no ini file
    # in any parent directory.
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "alembic.ini").exists()

    db_path = tmp_path / "bootstrap.sqlite3"
    url = f"sqlite:///{db_path}"

    run_alembic_upgrade(url)

    # Verify the schema applied: baseline must create the alembic_version
    # table plus the v1 domain tables.
    con = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        con.close()

    assert "alembic_version" in tables
    for required in ("jobs", "files", "pages", "analysis", "config_snapshots"):
        assert required in tables, f"migration did not create table {required!r}"


def test_packaged_migrations_tree_is_complete() -> None:
    """The wheel must ship ``env.py``, ``script.py.mako`` and at least
    one ``versions/*.py`` migration alongside the ``docunomnom.storage``
    package. A regression here would silently re-introduce the
    ``script_location`` CommandError in production."""
    pkg_dir = Path(next(iter(_packaged_migrations.__path__)))
    assert (pkg_dir / "env.py").is_file()
    assert (pkg_dir / "script.py.mako").is_file()
    versions = [p for p in (pkg_dir / "versions").glob("*.py") if p.name != "__init__.py"]
    assert versions, "no Alembic version scripts shipped with the package"


def test_migration_runs_with_explicit_ini(tmp_path: Path, monkeypatch) -> None:
    """Dev/CI convenience: passing an explicit ``alembic.ini`` path still
    works and pointedly overrides ``sqlalchemy.url`` with the caller's
    argument.

    The ini intentionally contains a different ``sqlalchemy.url`` — the
    bootstrap must override it with the value passed by the caller so
    env resolution (via ``Settings``) is always the source of truth.
    """
    ini = tmp_path / "alembic.ini"
    pkg_dir = Path(next(iter(_packaged_migrations.__path__)))
    # Mirror the logging sections expected by env.py's fileConfig call.
    ini.write_text(
        "[alembic]\n"
        f"script_location = {pkg_dir}\n"
        "sqlalchemy.url = sqlite:///should-be-overridden.sqlite3\n"
        "\n"
        "[loggers]\nkeys = root\n\n"
        "[handlers]\nkeys = console\n\n"
        "[formatters]\nkeys = generic\n\n"
        "[logger_root]\nlevel = WARNING\nhandlers = console\nqualname =\n\n"
        "[handler_console]\nclass = StreamHandler\n"
        "args = (sys.stderr,)\nlevel = NOTSET\nformatter = generic\n\n"
        "[formatter_generic]\nformat = %(levelname)s %(message)s\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "explicit.sqlite3"
    url = f"sqlite:///{db_path}"

    monkeypatch.chdir(tmp_path)
    run_alembic_upgrade(url, alembic_ini=ini)

    assert db_path.exists()
    # The wrong file from the ini's sqlalchemy.url must NOT have been
    # created (the override was honored).
    assert not (tmp_path / "should-be-overridden.sqlite3").exists()
    assert not Path(os.getcwd(), "should-be-overridden.sqlite3").exists()
