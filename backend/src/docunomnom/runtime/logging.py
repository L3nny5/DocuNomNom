"""Operational logging configuration for the worker and API processes.

Phase 6 standardizes one stdlib ``logging`` setup the whole app shares:

* Log level driven by ``settings.log_level`` (env: ``DOCUNOMNOM_LOG_LEVEL``).
* JSON-ish single-line records when ``DOCUNOMNOM_LOG_FORMAT=json`` (the
  TrueNAS / container default), otherwise classic human-readable lines.
* A small set of well-known operational event names (``LogEvent``) so
  log aggregators can filter without parsing free-text messages.

Sensitive content guard: do not log full OCR text or document content
at INFO/WARNING level. The pipeline events deliberately log *counts*
and *page indexes* only; page text and AI responses go to the database
audit trail instead.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Final

JSON_FORMAT_ENV = "DOCUNOMNOM_LOG_FORMAT"


class LogEvent:
    """Stable operational event vocabulary.

    These names show up in log records under the ``event`` field (when
    using JSON output). They are intentionally narrow; per-domain
    business events go through ``JobEventType`` and are persisted to
    the DB instead.
    """

    WORKER_STARTING: Final = "worker.starting"
    WORKER_READY: Final = "worker.ready"
    WORKER_STOPPING: Final = "worker.stopping"
    WORKER_PREFLIGHT_OK: Final = "worker.preflight.ok"
    WORKER_PREFLIGHT_FAIL: Final = "worker.preflight.fail"
    WORKER_LOCK_ACQUIRED: Final = "worker.lock.acquired"
    WORKER_LOCK_DENIED: Final = "worker.lock.denied"
    WORKER_SCAN_FAILED: Final = "worker.scan.failed"
    WORKER_DRAIN_FAILED: Final = "worker.drain.failed"
    JOB_FAILED: Final = "job.failed"
    JOB_CRASHED: Final = "job.crashed"
    DB_MIGRATION_OK: Final = "db.migration.ok"
    DB_MIGRATION_FAIL: Final = "db.migration.fail"
    API_STARTING: Final = "api.starting"


class _JsonFormatter(logging.Formatter):
    """Single-line JSON formatter that never raises on encoding errors."""

    _STD_KEYS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Promote any extra structured keys passed via logger.info(..., extra=...).
        for k, v in record.__dict__.items():
            if k in self._STD_KEYS or k.startswith("_"):
                continue
            try:
                json.dumps(v)
            except TypeError:
                payload[k] = repr(v)
            else:
                payload[k] = v
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = {
                "ts": payload["ts"],
                "level": payload["level"],
                "message": str(record.getMessage()),
            }
            return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, force_format: str | None = None) -> None:
    """Configure root logging once.

    Idempotent: re-calling replaces the root handler. ``force_format``
    overrides the ``DOCUNOMNOM_LOG_FORMAT`` env var (mostly for tests).
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    fmt = force_format if force_format is not None else os.environ.get(JSON_FORMAT_ENV, "text")
    if fmt.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root.addHandler(handler)
    try:
        root.setLevel(level.upper())
    except ValueError:
        root.setLevel(logging.INFO)

    # Tame a few chatty third-party loggers we never want at INFO in
    # production. Operators can still bump the global level.
    for noisy in ("uvicorn.access", "asyncio", "httpx"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
