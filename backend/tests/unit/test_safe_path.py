"""Tests for the path sandbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from docunomnom.storage.files.safe_path import UnsafePathError, is_inside, safe_path


def test_safe_path_accepts_simple_child(tmp_path: Path) -> None:
    p = safe_path(tmp_path, "foo.pdf")
    assert p == (tmp_path / "foo.pdf").resolve()


def test_safe_path_accepts_nested(tmp_path: Path) -> None:
    p = safe_path(tmp_path, "a", "b", "c.pdf")
    assert p == (tmp_path / "a" / "b" / "c.pdf").resolve()


def test_safe_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_path(tmp_path, "../etc/shadow")


def test_safe_path_rejects_absolute_outside(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_path(tmp_path, "/etc/shadow")


def test_safe_path_rejects_relative_root() -> None:
    with pytest.raises(UnsafePathError):
        safe_path("relative/root", "child")


def test_safe_path_follows_symlink_outside(tmp_path: Path) -> None:
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    (outside_root / "secret.txt").write_text("nope")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    link = sandbox / "escape"
    link.symlink_to(outside_root)

    with pytest.raises(UnsafePathError):
        safe_path(sandbox, "escape", "secret.txt")


def test_is_inside_true_for_child(tmp_path: Path) -> None:
    assert is_inside(tmp_path, "child.pdf") is True


def test_is_inside_false_for_traversal(tmp_path: Path) -> None:
    assert is_inside(tmp_path, "../escape.pdf") is False
