"""Production startup preflight checks.

Phase 6 hardening. The worker (and any process that drives jobs) calls
``run_preflight`` once before entering its main loop. Each check is
deterministic, side-effect free where possible, and produces an
operator-readable error when it fails.

The checks intentionally cover only invariants that v1 actually relies
on at runtime:

* All four bind-mount directories exist and are writable.
* ``work_dir`` and ``output_dir`` live on the same filesystem so the
  exporter's ``rename(2)`` is atomic (plan §15).
* ``work_dir`` and ``archive_dir`` live on the same filesystem when
  archiving is enabled (so archiving never silently degrades to copy).
* The SQLite database file does not live on a remote / unsafe mount
  (SMB / NFS / FUSE) where WAL guarantees do not hold (plan §3).
* AI configuration is internally coherent: ``mode != off`` requires a
  real backend, ``backend=openai`` requires ``allow_external_egress``,
  and the AI thresholds form a sane band (auto-export >= review-below).
* Splitter weights sum to roughly 1.0 (advisory, but caught here so a
  misconfigured deployment fails on startup, not on the first job).

In addition, ``acquire_single_worker_lock`` writes a PID file under
``work_dir`` to make the v1 single-worker invariant operationally
explicit. A second worker started against the same data dir refuses to
boot rather than racing on the queue.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from sqlalchemy.engine.url import make_url

from ..config import Settings
from ..core.models import AiBackend, AiMode, OcrBackend

logger = logging.getLogger("docunomnom.runtime.preflight")


PROBE_FILENAME = ".docunomnom_preflight_probe"
WORKER_LOCK_FILENAME = ".docunomnom_worker.lock"

# Filesystem types that do NOT provide the durability / locking
# semantics SQLite WAL relies on. We refuse to host the DB on these.
_UNSAFE_DB_FS_TYPES: frozenset[str] = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smb",
        "smb2",
        "smb3",
        "smbfs",
        "fuse",
        "fuse.sshfs",
        "fuse.rclone",
        "sshfs",
        "afpfs",
        "9p",
    }
)


class PreflightError(RuntimeError):
    """A preflight check failed; the process MUST NOT start."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """Result of a single preflight check."""

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """All preflight check results, in order."""

    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(c for c in self.checks if not c.ok)


# ---------------------------------------------------------------------------
# Path checks
# ---------------------------------------------------------------------------


def _check_directory(path: Path, label: str) -> PreflightCheck:
    name = f"path.{label}.writable"
    if not path.exists():
        return PreflightCheck(name=name, ok=False, detail=f"{label} {path} does not exist")
    if not path.is_dir():
        return PreflightCheck(name=name, ok=False, detail=f"{label} {path} is not a directory")
    probe = path / f"{PROBE_FILENAME}.{os.getpid()}"
    try:
        probe.write_bytes(b"")
    except OSError as exc:
        return PreflightCheck(
            name=name,
            ok=False,
            detail=f"{label} {path} is not writable: {exc}",
        )
    finally:
        with contextlib.suppress(OSError):
            probe.unlink(missing_ok=True)
    return PreflightCheck(name=name, ok=True, detail=str(path))


def _check_same_device(a: Path, b: Path, *, name: str) -> PreflightCheck:
    try:
        dev_a = a.stat().st_dev
        dev_b = b.stat().st_dev
    except OSError as exc:
        return PreflightCheck(name=name, ok=False, detail=str(exc))
    if dev_a != dev_b:
        return PreflightCheck(
            name=name,
            ok=False,
            detail=(
                f"{a} (dev={dev_a}) and {b} (dev={dev_b}) live on different "
                "filesystems; rename(2) would not be atomic"
            ),
        )
    return PreflightCheck(name=name, ok=True, detail=f"same device dev={dev_a}")


# ---------------------------------------------------------------------------
# SQLite path / mount checks
# ---------------------------------------------------------------------------


def _sqlite_file_path(database_url: str) -> Path | None:
    """Return the absolute path of a file-backed SQLite DB, or ``None``
    for in-memory / non-sqlite URLs."""
    try:
        url = make_url(database_url)
    except Exception:
        return None
    if url.get_backend_name() != "sqlite":
        return None
    db = url.database or ""
    if db in ("", ":memory:") or db.startswith("file::memory:"):
        return None
    return Path(db).resolve()


def _read_proc_mounts() -> tuple[tuple[str, str], ...]:
    """Return ``(mount_point, fs_type)`` pairs from ``/proc/mounts``.

    Returns an empty tuple on platforms that do not expose ``/proc/mounts``
    (e.g. macOS, Windows). The caller treats that as "cannot prove unsafe"
    and skips the check rather than failing.
    """
    proc = Path("/proc/mounts")
    if not proc.exists():
        return ()
    pairs: list[tuple[str, str]] = []
    try:
        for line in proc.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount_point = parts[1]
            fs_type = parts[2]
            pairs.append((mount_point, fs_type))
    except OSError:
        return ()
    return tuple(pairs)


def _classify_mount(
    path: Path,
    mounts: Iterable[tuple[str, str]],
) -> tuple[str, str] | None:
    """Return the ``(mount_point, fs_type)`` of the mount that contains
    ``path``, or ``None`` if no enclosing mount entry was found."""
    abs_path = str(path.resolve())
    best: tuple[str, str] | None = None
    best_len = -1
    for mp, fs in mounts:
        match = abs_path == mp or abs_path.startswith(mp.rstrip("/") + "/")
        if match and len(mp) > best_len:
            best = (mp, fs)
            best_len = len(mp)
    return best


def _check_sqlite_safe_mount(
    database_url: str,
    *,
    mounts_provider: Callable[[], tuple[tuple[str, str], ...]] = _read_proc_mounts,
) -> PreflightCheck:
    name = "sqlite.mount.safe"
    db_path = _sqlite_file_path(database_url)
    if db_path is None:
        return PreflightCheck(name=name, ok=True, detail="non-file or in-memory sqlite")
    mounts = mounts_provider()
    if not mounts:
        return PreflightCheck(
            name=name,
            ok=True,
            detail="no /proc/mounts available; mount-type check skipped",
        )
    classified = _classify_mount(db_path, mounts)
    if classified is None:
        return PreflightCheck(
            name=name,
            ok=True,
            detail=f"no enclosing mount found for {db_path}; assumed local",
        )
    _, fs_type = classified
    if fs_type.lower() in _UNSAFE_DB_FS_TYPES:
        return PreflightCheck(
            name=name,
            ok=False,
            detail=(
                f"sqlite database {db_path} lives on filesystem type "
                f"'{fs_type}', which does not provide the durability / "
                "locking guarantees WAL relies on. Move the DB to a local "
                "ZFS/ext4/xfs path."
            ),
        )
    return PreflightCheck(
        name=name,
        ok=True,
        detail=f"{db_path} on fs '{fs_type}'",
    )


# ---------------------------------------------------------------------------
# AI / network coherence
# ---------------------------------------------------------------------------


def _check_ai_coherence(settings: Settings) -> tuple[PreflightCheck, ...]:
    out: list[PreflightCheck] = []

    backend = settings.ai.backend
    mode = settings.ai.mode

    # Mode without backend.
    if mode != AiMode.OFF and backend == AiBackend.NONE:
        out.append(
            PreflightCheck(
                name="ai.mode_requires_backend",
                ok=False,
                detail=(
                    f"ai.mode='{mode.value}' requires ai.backend != 'none'. "
                    "Either pick an adapter or set ai.mode='off'."
                ),
            )
        )
    else:
        out.append(PreflightCheck(name="ai.mode_requires_backend", ok=True))

    # External egress for OpenAI.
    if backend == AiBackend.OPENAI:
        if not settings.network.allow_external_egress:
            out.append(
                PreflightCheck(
                    name="ai.openai_requires_egress",
                    ok=False,
                    detail=(
                        "ai.backend='openai' requires "
                        "network.allow_external_egress=true and an explicit "
                        "network.allowed_hosts list."
                    ),
                )
            )
        elif not settings.network.allowed_hosts:
            out.append(
                PreflightCheck(
                    name="ai.openai_requires_egress",
                    ok=False,
                    detail=(
                        "ai.backend='openai' requires at least one entry "
                        "in network.allowed_hosts (the OpenAI endpoint host)."
                    ),
                )
            )
        else:
            out.append(PreflightCheck(name="ai.openai_requires_egress", ok=True))

        api_key_env = settings.ai.openai.api_key_env
        if api_key_env and not os.environ.get(api_key_env):
            out.append(
                PreflightCheck(
                    name="ai.openai_api_key_present",
                    ok=False,
                    detail=(
                        f"ai.backend='openai' but environment variable "
                        f"'{api_key_env}' is unset; OpenAI calls would 401."
                    ),
                )
            )
        else:
            out.append(PreflightCheck(name="ai.openai_api_key_present", ok=True))

    # Threshold sanity.
    auto_min = settings.ai.thresholds.auto_export_min_confidence
    review_below = settings.ai.thresholds.review_required_below
    if auto_min < review_below:
        out.append(
            PreflightCheck(
                name="ai.thresholds_band",
                ok=False,
                detail=(
                    "ai.thresholds.auto_export_min_confidence "
                    f"({auto_min}) must be >= ai.thresholds.review_required_below "
                    f"({review_below})."
                ),
            )
        )
    else:
        out.append(PreflightCheck(name="ai.thresholds_band", ok=True))

    return tuple(out)


def _check_ocr_backend_available(
    settings: Settings,
    *,
    importer: Callable[[str], object] | None = None,
) -> PreflightCheck:
    """Fail fast when the selected OCR backend's Python dependencies
    are not importable in this interpreter.

    This catches the common Docker misconfiguration where the Debian
    ``ocrmypdf`` apt package is installed (which ships its Python
    module for the system Python) but the worker runs on a different
    Python (e.g. the ``python:3.12-slim-bookworm`` image's Python 3.12,
    which cannot see /usr/lib/python3/dist-packages). Without this
    check the worker boots fine and crashes on the first job with
    ``ocr_config_error: ocrmypdf is not installed`` — we want that
    failure at startup instead.

    ``external_api`` has no Python import to probe; its runtime
    requirements (egress + allowed_hosts + https) are covered by the
    AI/network coherence checks and by ``GenericExternalOcrAdapter``'s
    own validation at call time.
    """
    name = "ocr.backend_available"
    if settings.ocr.backend is not OcrBackend.OCRMYPDF:
        return PreflightCheck(name=name, ok=True, detail=f"backend={settings.ocr.backend.value}")

    import_fn = importer or __import__
    try:
        import_fn("ocrmypdf")
    except ImportError as exc:
        return PreflightCheck(
            name=name,
            ok=False,
            detail=(
                "ocr.backend='ocrmypdf' but the 'ocrmypdf' Python package is "
                f"not importable ({exc}). Install it into the worker's "
                "interpreter (e.g. `pip install 'docunomnom[ocr]'`) — the "
                "Debian apt package alone is not enough when the worker "
                "runs on a different Python than the system one."
            ),
        )
    return PreflightCheck(name=name, ok=True, detail="ocrmypdf importable")


def _check_splitter_weights(settings: Settings) -> PreflightCheck:
    s = settings.splitter
    total = s.keyword_weight + s.layout_weight + s.page_number_weight
    if not (0.99 <= total <= 1.01):
        return PreflightCheck(
            name="splitter.weights_sum",
            ok=False,
            detail=(
                "splitter weights must sum to 1.0 "
                f"(got {total:.3f}: keyword={s.keyword_weight}, "
                f"layout={s.layout_weight}, page_number={s.page_number_weight})."
            ),
        )
    return PreflightCheck(name="splitter.weights_sum", ok=True, detail=f"sum={total:.3f}")


def _check_pipeline_version(settings: Settings) -> PreflightCheck:
    name = "runtime.pipeline_version"
    pv = settings.runtime.pipeline_version
    if not pv or not re.match(r"^\d+\.\d+\.\d+", pv):
        return PreflightCheck(
            name=name,
            ok=False,
            detail=(
                f"runtime.pipeline_version must look like 'MAJOR.MINOR.PATCH' "
                f"(got {pv!r}); it is part of the run_key and must be stable."
            ),
        )
    return PreflightCheck(name=name, ok=True, detail=pv)


# ---------------------------------------------------------------------------
# Top-level preflight
# ---------------------------------------------------------------------------


def run_preflight(
    settings: Settings,
    *,
    mounts_provider: Callable[[], tuple[tuple[str, str], ...]] = _read_proc_mounts,
    raise_on_failure: bool = True,
) -> PreflightReport:
    """Run all preflight checks.

    When ``raise_on_failure`` is True (the production default) the
    function raises ``PreflightError`` on the first failure with an
    aggregated, operator-readable message. Tests usually pass
    ``raise_on_failure=False`` to inspect the full report.
    """
    checks: list[PreflightCheck] = []

    paths = settings.paths
    input_dir = Path(paths.input_dir)
    output_dir = Path(paths.output_dir)
    work_dir = Path(paths.work_dir)
    archive_dir = Path(paths.archive_dir)

    checks.append(_check_directory(input_dir, "input_dir"))
    checks.append(_check_directory(output_dir, "output_dir"))
    checks.append(_check_directory(work_dir, "work_dir"))
    checks.append(_check_directory(archive_dir, "archive_dir"))

    # Same-device requirements (only meaningful if both dirs exist).
    same_fs = settings.exporter.require_same_filesystem
    if same_fs and work_dir.exists() and output_dir.exists():
        checks.append(_check_same_device(work_dir, output_dir, name="exporter.same_device"))
    archive_on = settings.exporter.archive_after_export
    if same_fs and archive_on and work_dir.exists() and archive_dir.exists():
        checks.append(_check_same_device(work_dir, archive_dir, name="archiver.same_device"))

    checks.append(
        _check_sqlite_safe_mount(
            settings.storage.database_url,
            mounts_provider=mounts_provider,
        )
    )
    checks.extend(_check_ai_coherence(settings))
    checks.append(_check_ocr_backend_available(settings))
    checks.append(_check_splitter_weights(settings))
    checks.append(_check_pipeline_version(settings))

    report = PreflightReport(checks=tuple(checks))

    for c in report.checks:
        if c.ok:
            logger.info("preflight.ok name=%s detail=%s", c.name, c.detail)
        else:
            logger.error("preflight.fail name=%s detail=%s", c.name, c.detail)

    if not report.ok and raise_on_failure:
        failures = report.failures()
        primary = failures[0]
        message = "; ".join(f"{f.name}: {f.detail}" for f in failures)
        raise PreflightError(code=primary.name, message=message)

    return report


# ---------------------------------------------------------------------------
# Single-worker advisory lock
# ---------------------------------------------------------------------------


class SingleWorkerLockError(RuntimeError):
    """Another worker process appears to be running against the same data dir."""


@dataclass
class SingleWorkerLock:
    """Advisory PID-file lock under ``work_dir``.

    The lock is *advisory*: we trust the operator not to bypass it and
    we trust the OS to invalidate stale PIDs on reboot. The point is to
    make the v1 single-worker invariant explicit and to refuse a
    misconfigured second worker started by hand.
    """

    path: Path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def release(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink(missing_ok=True)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Some other process owns the PID; treat it as alive.
        return True
    except OSError:
        return False
    return True


def acquire_single_worker_lock(work_dir: Path) -> SingleWorkerLock:
    """Acquire (or steal a stale) PID-file lock under ``work_dir``.

    Raises ``SingleWorkerLockError`` when another process holding a live
    PID already owns the lock.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    lock_path = work_dir / WORKER_LOCK_FILENAME

    if lock_path.exists():
        try:
            existing = lock_path.read_text(encoding="utf-8").strip()
            existing_pid = int(existing) if existing else 0
        except (OSError, ValueError):
            existing_pid = 0
        if existing_pid and existing_pid != os.getpid() and _pid_is_alive(existing_pid):
            raise SingleWorkerLockError(
                f"another worker (pid={existing_pid}) already owns "
                f"{lock_path}; v1 requires single-worker deployment."
            )
        # Stale lock: overwrite it.
        logger.warning(
            "preflight.worker_lock.stale path=%s pid=%s; reclaiming",
            lock_path,
            existing_pid,
        )

    lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return SingleWorkerLock(path=lock_path)
