"""OCR artifact persistence policy.

Per plan §6:
- Page OCR text lives *in the DB* when it's small.
- A truncated copy + reference to the on-disk artifact is kept when it's
  large.
- The full searchable PDF (or any other large blob) is kept on disk under
  ``storage.ocr_artifact_dir``.

This module provides the small, deterministic helpers that decide whether
a given page text is "small enough" and that produce a stable on-disk path
for a job's OCR artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PageTextStorageDecision:
    """Result of deciding what to keep in the DB for a single page."""

    db_text: str
    truncated: bool


def decide_page_text_storage(
    text: str,
    *,
    max_inline_bytes: int,
) -> PageTextStorageDecision:
    """Return the version of ``text`` to persist in the ``pages`` table.

    The size budget is measured in UTF-8 bytes; the truncation point is the
    largest character boundary that still fits.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_inline_bytes:
        return PageTextStorageDecision(db_text=text, truncated=False)
    truncated = encoded[:max_inline_bytes].decode("utf-8", errors="ignore")
    return PageTextStorageDecision(db_text=truncated, truncated=True)


def artifact_path_for_job(
    *,
    artifact_root: Path,
    job_id: int,
    file_sha256: str,
    suffix: str,
) -> Path:
    """Return a deterministic on-disk path for an OCR artifact.

    Paths are sharded by the first 2 hex chars of the SHA-256 to avoid
    huge flat directories.
    """
    if not file_sha256 or len(file_sha256) < 2:
        raise ValueError("file_sha256 must be at least 2 hex chars")
    shard = file_sha256[:2]
    return artifact_root / shard / f"job-{job_id}-{file_sha256}{suffix}"


def store_artifact(
    *,
    artifact_root: Path,
    job_id: int,
    file_sha256: str,
    suffix: str,
    payload: bytes,
) -> Path:
    """Write ``payload`` to a deterministic artifact path and return it."""
    target = artifact_path_for_job(
        artifact_root=artifact_root,
        job_id=job_id,
        file_sha256=file_sha256,
        suffix=suffix,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target
