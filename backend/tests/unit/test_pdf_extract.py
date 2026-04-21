"""Tests for PDF utilities (page count, splitting, sidecar parsing)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from docunomnom.adapters.pdf import (
    PdfReadError,
    parse_sidecar_text,
    pdf_page_count,
    split_pdf_pages,
)


def _make_pdf(path: Path, *, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_pdf_page_count(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", pages=4)
    assert pdf_page_count(src) == 4


def test_pdf_page_count_invalid_path_raises(tmp_path: Path) -> None:
    with pytest.raises(PdfReadError):
        pdf_page_count(tmp_path / "missing.pdf")


def test_split_pdf_pages_writes_subrange(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", pages=5)
    target = tmp_path / "out.pdf"

    split_pdf_pages(src, target, start_page=2, end_page=4)

    reader = PdfReader(str(target))
    assert len(reader.pages) == 3


def test_split_pdf_pages_validates_range(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", pages=3)
    with pytest.raises(PdfReadError):
        split_pdf_pages(src, tmp_path / "out.pdf", start_page=0, end_page=1)
    with pytest.raises(PdfReadError):
        split_pdf_pages(src, tmp_path / "out.pdf", start_page=2, end_page=1)
    with pytest.raises(PdfReadError):
        split_pdf_pages(src, tmp_path / "out.pdf", start_page=1, end_page=10)


def test_parse_sidecar_text_normal() -> None:
    text = "page one\x0cpage two\x0cpage three"
    assert parse_sidecar_text(text, page_count=3) == ["page one", "page two", "page three"]


def test_parse_sidecar_text_trailing_formfeed_dropped() -> None:
    text = "a\x0cb\x0c"
    assert parse_sidecar_text(text, page_count=2) == ["a", "b"]


def test_parse_sidecar_text_pads_when_short() -> None:
    text = "only one"
    assert parse_sidecar_text(text, page_count=3) == ["only one", "", ""]


def test_parse_sidecar_text_truncates_when_long() -> None:
    text = "a\x0cb\x0cc\x0cd"
    assert parse_sidecar_text(text, page_count=2) == ["a", "b"]
