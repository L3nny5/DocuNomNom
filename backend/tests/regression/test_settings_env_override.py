"""Regression: the documented ``DOCUNOMNOM__SECTION__KEY`` (double-
underscore after the prefix) env convention must actually take effect.

Background: production compose sets::

    DOCUNOMNOM__STORAGE__DATABASE_URL=sqlite:////data/docunomnom.sqlite3

but the preflight log showed ``/app/data/docunomnom.sqlite3`` — the
built-in pydantic-settings env parser, with ``env_prefix='DOCUNOMNOM_'``
and ``env_nested_delimiter='__'``, expects the single-underscore form
``DOCUNOMNOM_STORAGE__DATABASE_URL`` and silently ignored the double-
underscore variant, so the model default leaked through.

This test pins the resolved ``storage.database_url`` to the env override
and verifies that the preflight's sqlite-path helper sees the same
absolute path that the runtime will actually open.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from docunomnom.config import Settings, reset_settings_cache
from docunomnom.runtime.preflight import _sqlite_file_path


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    reset_settings_cache()
    yield
    reset_settings_cache()


def _clear_docunomnom_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop any DOCUNOMNOM_* vars inherited from the test runner so that
    this test is hermetic no matter what the operator exported."""
    import os

    for key in list(os.environ):
        if key.upper().startswith("DOCUNOMNOM"):
            monkeypatch.delenv(key, raising=False)


def test_double_underscore_env_overrides_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact env name used in ``compose.truenas.yaml`` must resolve."""
    _clear_docunomnom_env(monkeypatch)
    monkeypatch.setenv(
        "DOCUNOMNOM__STORAGE__DATABASE_URL",
        "sqlite:////data/docunomnom.sqlite3",
    )

    s = Settings()

    assert s.storage.database_url == "sqlite:////data/docunomnom.sqlite3"


def test_preflight_path_matches_runtime_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preflight must resolve the SQLite path from the same URL the
    worker will actually open; no leakage of the ``./data/...`` default."""
    _clear_docunomnom_env(monkeypatch)
    monkeypatch.setenv(
        "DOCUNOMNOM__STORAGE__DATABASE_URL",
        "sqlite:////data/docunomnom.sqlite3",
    )

    s = Settings()
    resolved = _sqlite_file_path(s.storage.database_url)

    assert resolved is not None
    # Four slashes after ``sqlite:`` means an absolute path; the resolved
    # filesystem path must be the absolute /data location, NOT a CWD-
    # relative ``/app/data/docunomnom.sqlite3``.
    assert str(resolved) == "/data/docunomnom.sqlite3"


def test_single_underscore_env_still_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backwards-compat: the pydantic-settings native
    ``DOCUNOMNOM_SECTION__KEY`` form (as used by the existing unit
    tests) must keep working."""
    _clear_docunomnom_env(monkeypatch)
    monkeypatch.setenv("DOCUNOMNOM_WORKER__MAX_ATTEMPTS", "9")

    s = Settings()

    assert s.worker.max_attempts == 9


def test_double_underscore_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Env precedence: the double-underscore form must beat a value
    coming from the YAML layer, same as the built-in env source does."""
    _clear_docunomnom_env(monkeypatch)
    cfg = tmp_path / "custom.yaml"
    cfg.write_text(
        "storage:\n  database_url: sqlite:///./data/from-yaml.sqlite3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUNOMNOM_CONFIG", str(cfg))
    monkeypatch.setenv(
        "DOCUNOMNOM__STORAGE__DATABASE_URL",
        "sqlite:////data/docunomnom.sqlite3",
    )

    s = Settings()

    assert s.storage.database_url == "sqlite:////data/docunomnom.sqlite3"
