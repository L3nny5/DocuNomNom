"""Filesystem helpers (sandbox, atomic writes, OCR artifact persistence)."""

from .atomic import (
    CrossDeviceError,
    archive_original,
    assert_same_device,
    atomic_publish,
    collision_safe_name,
    fsync_dir,
    fsync_file,
)
from .ocr_artifacts import (
    PageTextStorageDecision,
    artifact_path_for_job,
    decide_page_text_storage,
    store_artifact,
)
from .safe_path import UnsafePathError, is_inside, safe_path

__all__ = [
    "CrossDeviceError",
    "PageTextStorageDecision",
    "UnsafePathError",
    "archive_original",
    "artifact_path_for_job",
    "assert_same_device",
    "atomic_publish",
    "collision_safe_name",
    "decide_page_text_storage",
    "fsync_dir",
    "fsync_file",
    "is_inside",
    "safe_path",
    "store_artifact",
]
