"""Tests for OCR artifact persistence policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from docunomnom.storage.files import (
    artifact_path_for_job,
    decide_page_text_storage,
    store_artifact,
)


def test_small_text_kept_in_full() -> None:
    decision = decide_page_text_storage("hello", max_inline_bytes=1024)
    assert decision.db_text == "hello"
    assert decision.truncated is False


def test_large_text_truncated_to_byte_budget() -> None:
    text = "x" * 5000
    decision = decide_page_text_storage(text, max_inline_bytes=128)
    assert decision.truncated is True
    assert len(decision.db_text.encode("utf-8")) <= 128


def test_truncation_handles_multibyte_characters() -> None:
    # Each "ä" is 2 bytes in UTF-8. Budget of 5 bytes => at most 2 ä's.
    text = "ä" * 10
    decision = decide_page_text_storage(text, max_inline_bytes=5)
    assert decision.truncated is True
    assert decision.db_text == "ää"


def test_artifact_path_is_sharded(tmp_path: Path) -> None:
    p = artifact_path_for_job(
        artifact_root=tmp_path,
        job_id=42,
        file_sha256="ab" + "0" * 62,
        suffix=".pdf",
    )
    assert p.parent.name == "ab"
    assert p.name == f"job-42-{'ab' + '0' * 62}.pdf"


def test_artifact_path_rejects_short_hash(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        artifact_path_for_job(
            artifact_root=tmp_path,
            job_id=1,
            file_sha256="",
            suffix=".pdf",
        )


def test_store_artifact_creates_parent_and_writes_payload(tmp_path: Path) -> None:
    target = store_artifact(
        artifact_root=tmp_path,
        job_id=7,
        file_sha256="cd" + "1" * 62,
        suffix=".txt",
        payload=b"hello",
    )
    assert target.read_bytes() == b"hello"
    assert target.parent.is_dir()
