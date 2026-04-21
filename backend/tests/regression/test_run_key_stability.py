"""Regression: ``run_key`` derivation MUST stay byte-stable across refactors.

The watcher's deduplication and the disaster-recovery path documented in
``docs/backups.md`` ("re-feed the archive into the input dir, dedupe by
run_key") both rely on this. Any silent change to the hashing scheme
would re-import every previously-exported document.
"""

from __future__ import annotations

import hashlib

from docunomnom.core.run_key import (
    compute_config_snapshot_hash,
    compute_run_key,
)

# Pinned values. If you have to update either of these, you ALSO have to
# write a migration story for existing deployments — do not change them
# casually. Both values were captured against the v1.0.0 implementation.
_PINNED_CONFIG_HASH = "bfa6ceebf136e4837ec687f2be09f612c645c9ec1f99e3ef5d497b0d5bb99e0a"
_PINNED_RUN_KEY = "8d3f5dbdab0c89ecd87b4d0156e589bd21ed7b675c08b02a1e6a68ed8e499d0d"


def test_config_snapshot_hash_is_stable() -> None:
    payload = {"a": 1, "b": [1, 2, 3]}
    assert compute_config_snapshot_hash(payload) == _PINNED_CONFIG_HASH


def test_config_snapshot_hash_is_key_order_independent() -> None:
    a = compute_config_snapshot_hash({"a": 1, "b": 2, "c": 3})
    b = compute_config_snapshot_hash({"c": 3, "b": 2, "a": 1})
    assert a == b


def test_config_snapshot_hash_distinguishes_values() -> None:
    a = compute_config_snapshot_hash({"x": 1})
    b = compute_config_snapshot_hash({"x": 2})
    assert a != b


def test_run_key_is_deterministic() -> None:
    rk_a = compute_run_key(
        file_sha256="f" * 64,
        config_snapshot_hash="c" * 64,
        pipeline_version="1.0.0",
    )
    rk_b = compute_run_key(
        file_sha256="f" * 64,
        config_snapshot_hash="c" * 64,
        pipeline_version="1.0.0",
    )
    assert rk_a == rk_b


def test_run_key_changes_when_pipeline_version_changes() -> None:
    rk_a = compute_run_key(
        file_sha256="f" * 64,
        config_snapshot_hash="c" * 64,
        pipeline_version="1.0.0",
    )
    rk_b = compute_run_key(
        file_sha256="f" * 64,
        config_snapshot_hash="c" * 64,
        pipeline_version="1.0.1",
    )
    assert rk_a != rk_b


def test_run_key_pinned_value() -> None:
    """Byte-stability check. If this changes, see module docstring."""
    rk = compute_run_key(
        file_sha256="<file>",
        config_snapshot_hash="<cfg>",
        pipeline_version="<pipeline_version>",
    )
    expected = hashlib.sha256(b"<file>|<cfg>|<pipeline_version>").hexdigest()
    assert rk == expected
    assert rk == _PINNED_RUN_KEY
