"""Tests for the atomic exporter and archiver helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from docunomnom.storage.files import (
    CrossDeviceError,
    archive_original,
    assert_same_device,
    atomic_publish,
    collision_safe_name,
)


def _write(p: Path, data: bytes = b"hello") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_atomic_publish_renames_into_target(tmp_path: Path) -> None:
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    src = _write(work / "draft.pdf", b"PDF-DATA")

    result = atomic_publish(
        source_path=src,
        target_dir=out,
        desired_name="invoice.pdf",
    )

    assert result == out / "invoice.pdf"
    assert result.read_bytes() == b"PDF-DATA"
    assert not src.exists()


def test_atomic_publish_collision_safe_naming(tmp_path: Path) -> None:
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    _write(out / "doc.pdf", b"existing")
    src = _write(work / "draft.pdf", b"new")

    result = atomic_publish(source_path=src, target_dir=out, desired_name="doc.pdf")

    assert result.name == "doc_2.pdf"
    assert (out / "doc.pdf").read_bytes() == b"existing"
    assert (out / "doc_2.pdf").read_bytes() == b"new"


def test_collision_safe_name_increments_until_free(tmp_path: Path) -> None:
    target = tmp_path
    _write(target / "a.pdf")
    _write(target / "a_2.pdf")
    assert collision_safe_name(target, "a.pdf") == "a_3.pdf"
    assert collision_safe_name(target, "fresh.pdf") == "fresh.pdf"


def test_assert_same_device_passes_for_same_dir(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert_same_device(a, b)  # must not raise


def test_atomic_publish_no_partial_file_visible(tmp_path: Path) -> None:
    """The target dir never contains a temp/in-progress file mid-publish."""
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    src = _write(work / "draft.pdf", b"X" * 1024)

    atomic_publish(source_path=src, target_dir=out, desired_name="final.pdf")

    listing = sorted(p.name for p in out.iterdir())
    assert listing == ["final.pdf"]


def test_archive_original_moves_to_archive_dir(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    arc = tmp_path / "arc"
    src_dir.mkdir()
    arc.mkdir()
    src = _write(src_dir / "scan.pdf", b"orig")

    result = archive_original(source_path=src, archive_dir=arc)

    assert result == arc / "scan.pdf"
    assert result.read_bytes() == b"orig"
    assert not src.exists()


def test_archive_original_collision_safe(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    arc = tmp_path / "arc"
    src_dir.mkdir()
    arc.mkdir()
    _write(arc / "scan.pdf", b"old")
    src = _write(src_dir / "scan.pdf", b"new")

    result = archive_original(source_path=src, archive_dir=arc)

    assert result.name == "scan_2.pdf"
    assert (arc / "scan.pdf").read_bytes() == b"old"


def test_assert_same_device_can_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    real_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> object:
        result = real_stat(self)
        if self == b:

            class _S:
                st_dev = result.st_dev + 1

            return _S()
        return result

    monkeypatch.setattr(Path, "stat", fake_stat, raising=True)
    with pytest.raises(CrossDeviceError):
        assert_same_device(a, b)
