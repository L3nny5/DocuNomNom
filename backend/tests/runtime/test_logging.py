"""Tests for the runtime logging configuration."""

from __future__ import annotations

import json
import logging

import pytest

from docunomnom.runtime.logging import LogEvent, configure_logging


def test_configure_logging_text_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", force_format="text")
    logging.getLogger("docunomnom.test").info("hello %s", LogEvent.WORKER_READY)
    captured = capsys.readouterr().err
    assert "INFO" in captured
    assert LogEvent.WORKER_READY in captured


def test_configure_logging_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", force_format="json")
    logging.getLogger("docunomnom.test").info(
        "ready", extra={"event": LogEvent.WORKER_READY, "pid": 1234}
    )
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["level"] == "INFO"
    assert record["message"] == "ready"
    assert record["event"] == LogEvent.WORKER_READY
    assert record["pid"] == 1234


def test_configure_logging_replaces_handlers(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", force_format="text")
    configure_logging("DEBUG", force_format="text")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_configure_logging_invalid_level_falls_back_to_info() -> None:
    configure_logging("nonsense", force_format="text")
    assert logging.getLogger().level == logging.INFO


def test_log_event_namespace_is_stable() -> None:
    assert LogEvent.WORKER_STARTING.startswith("worker.")
    assert LogEvent.JOB_FAILED == "job.failed"
    assert LogEvent.WORKER_PREFLIGHT_FAIL == "worker.preflight.fail"
