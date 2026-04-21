"""Runtime hardening helpers (Phase 6).

This package owns the production startup checks the worker (and the API
when it shares a process) runs before serving requests or processing
jobs. The goal is to fail fast with a clear, operator-friendly message
when the deployment is unsafe.
"""

from .logging import LogEvent, configure_logging
from .preflight import (
    PreflightCheck,
    PreflightError,
    PreflightReport,
    SingleWorkerLock,
    SingleWorkerLockError,
    acquire_single_worker_lock,
    run_preflight,
)

__all__ = [
    "LogEvent",
    "PreflightCheck",
    "PreflightError",
    "PreflightReport",
    "SingleWorkerLock",
    "SingleWorkerLockError",
    "acquire_single_worker_lock",
    "configure_logging",
    "run_preflight",
]
