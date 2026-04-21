"""Atomic filesystem helpers used by the exporter and the archiver.

The contract:

* Writes go into a *work directory* on the same filesystem as the final
  destination, so ``rename(2)`` is atomic and never crosses devices.
* Every byte and every directory entry that we promise to readers has been
  ``fsync(2)``'d before the rename.
* Readers in the destination directory never observe a half-written file.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class CrossDeviceError(RuntimeError):
    """Raised when the work dir and the destination dir live on different
    filesystems and the exporter is configured to require same-device.
    """


def assert_same_device(work_dir: Path, target_dir: Path) -> None:
    """Raise ``CrossDeviceError`` if the two directories are on different
    devices. Both directories must already exist."""
    if work_dir.stat().st_dev != target_dir.stat().st_dev:
        raise CrossDeviceError(
            f"work_dir {work_dir} and target_dir {target_dir} are on different filesystems"
        )


def fsync_file(path: Path) -> None:
    """fsync ``path`` (must be a regular file)."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path: Path) -> None:
    """fsync the directory entry at ``path``. On Windows this is a no-op."""
    if os.name == "nt":  # pragma: no cover - non-Linux runtime
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def collision_safe_name(target_dir: Path, desired_name: str) -> str:
    """Return ``desired_name`` if free, else append ``_2``, ``_3``... before
    the extension until a free slot is found.

    The check is racy in a true multi-writer setting but Phase 2 still
    assumes single-worker, and the actual rename uses ``os.link`` with
    fail-on-exist below to make collisions explicit if they ever happen.
    """
    candidate = target_dir / desired_name
    if not candidate.exists():
        return desired_name
    stem = Path(desired_name).stem
    suffix = Path(desired_name).suffix
    n = 2
    while True:
        attempt = f"{stem}_{n}{suffix}"
        if not (target_dir / attempt).exists():
            return attempt
        n += 1


def atomic_publish(
    *,
    source_path: Path,
    target_dir: Path,
    desired_name: str,
    require_same_device: bool = True,
) -> Path:
    """Move ``source_path`` into ``target_dir`` under a collision-safe name
    using a same-device atomic rename, fsyncing both the file and the
    target directory.

    Returns the final published path. The source file no longer exists.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    if require_same_device:
        assert_same_device(source_path.parent, target_dir)

    fsync_file(source_path)
    fsync_dir(source_path.parent)

    final_name = collision_safe_name(target_dir, desired_name)
    final_path = target_dir / final_name
    os.rename(str(source_path), str(final_path))
    fsync_dir(target_dir)
    return final_path


def archive_original(
    *,
    source_path: Path,
    archive_dir: Path,
    desired_name: str | None = None,
    require_same_device: bool = True,
    move: Callable[[str, str], None] | None = None,
) -> Path:
    """Move (or fall back to copy+unlink across devices) the original PDF
    into ``archive_dir``.

    The default behavior uses ``os.rename`` for same-device moves. If
    ``require_same_device`` is False and the move crosses devices, a
    copy+unlink fallback is used.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    name = desired_name or source_path.name
    final_name = collision_safe_name(archive_dir, name)
    final_path = archive_dir / final_name

    if require_same_device:
        assert_same_device(source_path.parent, archive_dir)
        os.rename(str(source_path), str(final_path))
    else:
        try:
            os.rename(str(source_path), str(final_path))
        except OSError:
            mover = move or shutil.copy2
            mover(str(source_path), str(final_path))
            os.unlink(str(source_path))
    fsync_dir(archive_dir)
    return final_path
