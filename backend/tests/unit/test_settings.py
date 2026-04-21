"""Tests for layered configuration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from docunomnom.config import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_defaults_loaded_from_bundled_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCUNOMNOM_CONFIG", raising=False)
    s = Settings()
    assert s.runtime.pipeline_version == "1.0.0"
    assert s.ingestion.poll_interval_seconds == 5.0
    assert s.worker.max_attempts == 3
    assert ".*" in s.ingestion.ignore_patterns


def test_yaml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "custom.yaml"
    cfg.write_text(
        """
ingestion:
  poll_interval_seconds: 1.5
  stability_window_seconds: 0.5
worker:
  max_attempts: 7
runtime:
  pipeline_version: "2.0.0"
"""
    )
    monkeypatch.setenv("DOCUNOMNOM_CONFIG", str(cfg))
    s = Settings()
    assert s.runtime.pipeline_version == "2.0.0"
    assert s.ingestion.poll_interval_seconds == 1.5
    assert s.ingestion.stability_window_seconds == 0.5
    assert s.worker.max_attempts == 7


def test_env_var_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "custom.yaml"
    cfg.write_text("worker:\n  max_attempts: 7\n")
    monkeypatch.setenv("DOCUNOMNOM_CONFIG", str(cfg))
    monkeypatch.setenv("DOCUNOMNOM_WORKER__MAX_ATTEMPTS", "9")
    s = Settings()
    assert s.worker.max_attempts == 9


def test_defaults_used_when_yaml_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCUNOMNOM_CONFIG", str(tmp_path / "does_not_exist.yaml"))
    s = Settings()
    assert s.runtime.pipeline_version == "1.0.0"


def test_validation_rejects_bad_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("DOCUNOMNOM_WORKER__MAX_ATTEMPTS", "0")
    with pytest.raises(ValidationError):
        Settings()
