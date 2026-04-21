"""Reprocessing key computation.

A ``run_key`` uniquely identifies a (file, configuration, pipeline_version)
tuple. Because ``files.sha256`` is intentionally not unique, the run_key is
what enforces "do not reprocess the same combination twice while one is still
active". See plan §5.

The hash function and component order are stable parts of the public contract;
do not change them without a migration plan, otherwise existing run_keys would
no longer match.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_config_snapshot_hash(payload: dict[str, Any]) -> str:
    """Deterministic digest of a config snapshot payload."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_run_key(
    *,
    file_sha256: str,
    config_snapshot_hash: str,
    pipeline_version: str,
) -> str:
    """Compute the run_key for a job."""
    if not file_sha256 or not config_snapshot_hash or not pipeline_version:
        raise ValueError("run_key components must all be non-empty")
    parts = "|".join((file_sha256, config_snapshot_hash, pipeline_version))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()
