"""File stability watcher.

Scans the input directory and creates a ``Job`` once a file has been observed
unchanged for ``stability_window_seconds``. Implements:

- ignore-pattern filtering (glob, applied to the basename),
- PDF magic-header check (``%PDF-``),
- size / mtime / inode stability tracking across scans,
- SHA-256 computation *after* stability is confirmed,
- ``run_key`` derivation from (file_sha256, config_snapshot.hash, pipeline_version),
- skipping files that already have an active job for the same ``run_key``.

The watcher is intentionally pure-Python and polling-based (no inotify) so
behavior is identical on TrueNAS bind mounts and local dev.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import IngestionSettings, Settings
from ..core.events import JobEventType
from ..core.models import (
    ConfigSnapshot,
    File,
    Job,
    JobEvent,
    JobStatus,
)
from ..core.ports.clock import ClockPort
from ..core.ports.storage import (
    ConfigSnapshotRepositoryPort,
    FileRepositoryPort,
    JobEventRepositoryPort,
    JobRepositoryPort,
)
from ..core.run_key import compute_config_snapshot_hash, compute_run_key

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
PDF_MAGIC_LEN = len(PDF_MAGIC)
SHA256_CHUNK_SIZE = 1024 * 1024  # 1 MiB


@dataclass(frozen=True, slots=True)
class FileSignature:
    """Stability signature for a file. Two signatures equal iff the file has
    not changed."""

    size: int
    mtime_ns: int
    inode: int


@dataclass(slots=True)
class _Observation:
    signature: FileSignature
    first_seen_at: datetime


@dataclass(slots=True)
class WatcherResult:
    """Per-scan outcome (used for tests and logging)."""

    enqueued_jobs: list[int]
    skipped_unstable: list[Path]
    skipped_active_run_key: list[Path]
    skipped_ignored: list[Path]
    skipped_invalid: list[Path]


def _is_ignored(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pat) for pat in patterns)


def _file_signature(path: Path) -> FileSignature:
    st = path.stat()
    return FileSignature(size=st.st_size, mtime_ns=st.st_mtime_ns, inode=st.st_ino)


def _has_pdf_magic(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(PDF_MAGIC_LEN)
    except OSError:
        return False
    return head == PDF_MAGIC


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(SHA256_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _mtime_to_dt(mtime_ns: int) -> datetime:
    """Convert ``stat()`` mtime (nanoseconds since epoch) to a *naive* UTC
    ``datetime``, matching the application-wide convention."""
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC).replace(tzinfo=None)


def settings_to_config_snapshot(settings: Settings) -> ConfigSnapshot:
    """Build the ``ConfigSnapshot`` for the current process configuration.

    The snapshot hash MUST change whenever any setting that influences
    pipeline behavior changes; reprocessing keys are derived from it.
    Sections that *only* affect operational concerns (poll intervals,
    log level) are intentionally excluded so trivial knob changes do not
    invalidate completed runs.
    """
    payload: dict[str, object] = {
        "pipeline_version": settings.runtime.pipeline_version,
        "ingestion": settings.ingestion.model_dump(mode="json"),
        "ocr": settings.ocr.model_dump(mode="json"),
        "splitter": settings.splitter.model_dump(mode="json"),
        "exporter": _exporter_payload(settings),
        "ai": settings.ai.model_dump(mode="json"),
    }
    return ConfigSnapshot(
        hash=compute_config_snapshot_hash(payload),
        ai_backend=settings.ai.backend,
        ai_mode=settings.ai.mode,
        ocr_backend=settings.ocr.backend,
        pipeline_version=settings.runtime.pipeline_version,
        payload=payload,
    )


def _exporter_payload(settings: Settings) -> dict[str, object]:
    """Filter exporter settings to the parts that change *output* contents.

    Operational toggles like ``require_same_filesystem`` do not change what
    we emit, only how we emit it, so they don't belong in the snapshot.
    """
    src = settings.exporter.model_dump(mode="json")
    return {
        "archive_after_export": src["archive_after_export"],
        "output_basename_template": src["output_basename_template"],
        "review_all_splits": src["review_all_splits"],
    }


class StabilityWatcher:
    """Watcher with explicit ports / dependencies for testability."""

    def __init__(
        self,
        *,
        input_dir: Path,
        ingestion: IngestionSettings,
        pipeline_version: str,
        clock: ClockPort,
        files: FileRepositoryPort,
        jobs: JobRepositoryPort,
        events: JobEventRepositoryPort,
        snapshots: ConfigSnapshotRepositoryPort,
        snapshot_factory: Callable[[], ConfigSnapshot],
    ) -> None:
        self._input_dir = input_dir
        self._ingestion = ingestion
        self._pipeline_version = pipeline_version
        self._clock = clock
        self._files = files
        self._jobs = jobs
        self._events = events
        self._snapshots = snapshots
        self._snapshot_factory = snapshot_factory
        self._observed: dict[Path, _Observation] = {}

    def _list_candidates(self) -> list[Path]:
        if not self._input_dir.exists():
            return []
        return sorted(p for p in self._input_dir.iterdir() if p.is_file())

    def scan_once(self) -> WatcherResult:
        """Perform one scan pass over the input directory."""
        result = WatcherResult(
            enqueued_jobs=[],
            skipped_unstable=[],
            skipped_active_run_key=[],
            skipped_ignored=[],
            skipped_invalid=[],
        )
        now = self._clock.now()
        seen_paths: set[Path] = set()

        for path in self._list_candidates():
            seen_paths.add(path)
            name = path.name
            if _is_ignored(name, self._ingestion.ignore_patterns):
                result.skipped_ignored.append(path)
                self._observed.pop(path, None)
                continue
            if not name.lower().endswith(".pdf"):
                result.skipped_invalid.append(path)
                self._observed.pop(path, None)
                continue

            try:
                signature = _file_signature(path)
            except FileNotFoundError:
                self._observed.pop(path, None)
                continue

            obs = self._observed.get(path)
            if obs is None or obs.signature != signature:
                self._observed[path] = _Observation(signature=signature, first_seen_at=now)
                result.skipped_unstable.append(path)
                continue

            elapsed = (now - obs.first_seen_at).total_seconds()
            if elapsed < self._ingestion.stability_window_seconds:
                result.skipped_unstable.append(path)
                continue

            if self._ingestion.require_pdf_magic and not _has_pdf_magic(path):
                result.skipped_invalid.append(path)
                self._observed.pop(path, None)
                continue

            try:
                job_id = self._enqueue(path, signature, result)
            except Exception:
                logger.exception("watcher: failed to enqueue job for %s", path)
                continue
            if job_id is not None:
                result.enqueued_jobs.append(job_id)
            # Either way, drop the observation so the next change re-arms it.
            self._observed.pop(path, None)

        # Forget files that disappeared between scans.
        for path in list(self._observed.keys()):
            if path not in seen_paths:
                self._observed.pop(path, None)

        return result

    def _enqueue(
        self,
        path: Path,
        signature: FileSignature,
        result: WatcherResult,
    ) -> int | None:
        sha256 = _sha256_file(path)
        snapshot = self._snapshots.get_or_create(self._snapshot_factory())
        if snapshot.id is None:
            raise RuntimeError("snapshot was not persisted (id is None)")

        run_key = compute_run_key(
            file_sha256=sha256,
            config_snapshot_hash=snapshot.hash,
            pipeline_version=self._pipeline_version,
        )

        if self._jobs.has_active_with_run_key(run_key):
            result.skipped_active_run_key.append(path)
            return None

        file_entity = self._files.add(
            File(
                sha256=sha256,
                original_name=path.name,
                size=signature.size,
                mtime=_mtime_to_dt(signature.mtime_ns),
                source_path=str(path),
            )
        )
        if file_entity.id is None:
            raise RuntimeError("file was not persisted (id is None)")

        job = self._jobs.add(
            Job(
                file_id=file_entity.id,
                status=JobStatus.PENDING,
                mode=snapshot.ai_mode,
                run_key=run_key,
                config_snapshot_id=snapshot.id,
                pipeline_version=self._pipeline_version,
            )
        )
        if job.id is None:
            raise RuntimeError("job was not persisted (id is None)")

        self._events.append(
            JobEvent(
                job_id=job.id,
                type=JobEventType.ENQUEUED.value,
                payload={
                    "path": str(path),
                    "sha256": sha256,
                    "run_key": run_key,
                    "snapshot_id": snapshot.id,
                    "snapshot_hash": snapshot.hash,
                },
            )
        )
        logger.info("watcher: enqueued job=%s for %s", job.id, path)
        return job.id
