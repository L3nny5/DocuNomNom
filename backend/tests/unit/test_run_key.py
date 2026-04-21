"""Tests for ``compute_run_key`` and ``compute_config_snapshot_hash``."""

from __future__ import annotations

import hashlib

import pytest

from docunomnom.core.run_key import (
    compute_config_snapshot_hash,
    compute_run_key,
)

FILE_A = "a" * 64
FILE_C = "c" * 64
CFG_B = "b" * 64
CFG_D = "d" * 64


def test_run_key_is_deterministic() -> None:
    a = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    b = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    assert a == b


def test_run_key_changes_when_file_changes() -> None:
    a = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    b = compute_run_key(file_sha256=FILE_C, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    assert a != b


def test_run_key_changes_when_config_changes() -> None:
    a = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    b = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_D, pipeline_version="1.0.0")
    assert a != b


def test_run_key_changes_when_pipeline_version_changes() -> None:
    a = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    b = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.1.0")
    assert a != b


def test_run_key_rejects_empty_components() -> None:
    with pytest.raises(ValueError):
        compute_run_key(file_sha256="", config_snapshot_hash="x", pipeline_version="1")
    with pytest.raises(ValueError):
        compute_run_key(file_sha256="x", config_snapshot_hash="", pipeline_version="1")
    with pytest.raises(ValueError):
        compute_run_key(file_sha256="x", config_snapshot_hash="y", pipeline_version="")


def test_run_key_format_is_hex_sha256() -> None:
    key = compute_run_key(file_sha256=FILE_A, config_snapshot_hash=CFG_B, pipeline_version="1.0.0")
    assert len(key) == 64
    int(key, 16)


def test_config_snapshot_hash_is_key_order_independent() -> None:
    a = compute_config_snapshot_hash({"a": 1, "b": 2, "c": [1, 2, 3]})
    b = compute_config_snapshot_hash({"c": [1, 2, 3], "b": 2, "a": 1})
    assert a == b


def test_config_snapshot_hash_known_value() -> None:
    payload = {"x": 1}
    expected = hashlib.sha256(b'{"x":1}').hexdigest()
    assert compute_config_snapshot_hash(payload) == expected
