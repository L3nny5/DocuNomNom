"""Tests for the OCRmyPDF adapter using a fake runner.

The real ``ocrmypdf`` binary is not invoked; we substitute a ``runner``
callable that produces the output PDF and the sidecar text file the same way
ocrmypdf would.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter

from docunomnom.adapters.ocr import OcrConfigError, OcrmypdfAdapter
from docunomnom.config import OcrmypdfSettings


def _make_pdf(path: Path, *, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _fake_runner(*, sidecar_pages: list[str]) -> Any:
    """Return a runner that writes a 2-page PDF and a sidecar text file."""

    def runner(**kwargs: Any) -> None:
        out = Path(kwargs["output_file"])
        side = Path(kwargs["sidecar"])
        # Write an output PDF matching the requested page count.
        _make_pdf(out, pages=len(sidecar_pages))
        side.write_text("\x0c".join(sidecar_pages), encoding="utf-8")

    return runner


def _copy_sanitizer(source: Path, cleaned: Path) -> None:
    """Test sanitizer that preserves input bytes without shelling out."""
    shutil.copyfile(source, cleaned)


def test_ocrmypdf_adapter_normalizes_pages(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf", pages=2)
    work = tmp_path / "work"
    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(),
        work_dir=work,
        runner=_fake_runner(sidecar_pages=["page one text", "page two text"]),
        sanitizer=_copy_sanitizer,
    )

    result = adapter.ocr_pdf(str(src), languages=("eng",))

    assert len(result.pages) == 2
    assert result.pages[0].page_no == 1 and result.pages[0].text == "page one text"
    assert result.pages[1].page_no == 2 and result.pages[1].text == "page two text"
    assert result.artifact_path is not None
    assert Path(result.artifact_path).exists()


def test_ocrmypdf_adapter_passes_language_string(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf", pages=1)
    work = tmp_path / "work"

    seen: dict[str, Any] = {}

    def runner(**kwargs: Any) -> None:
        seen.update(kwargs)
        out = Path(kwargs["output_file"])
        side = Path(kwargs["sidecar"])
        _make_pdf(out, pages=1)
        side.write_text("hello", encoding="utf-8")

    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(),
        work_dir=work,
        runner=runner,
        sanitizer=_copy_sanitizer,
    )
    adapter.ocr_pdf(str(src), languages=("eng", "deu"))

    assert seen["language"] == "eng+deu"
    assert seen["progress_bar"] is False


def test_ocrmypdf_adapter_missing_source_raises(tmp_path: Path) -> None:
    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(),
        work_dir=tmp_path / "work",
        runner=_fake_runner(sidecar_pages=["x"]),
        sanitizer=_copy_sanitizer,
    )
    with pytest.raises(OcrConfigError):
        adapter.ocr_pdf(str(tmp_path / "missing.pdf"))


def test_ocrmypdf_adapter_short_sidecar_pads(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf", pages=3)

    def runner(**kwargs: Any) -> None:
        out = Path(kwargs["output_file"])
        side = Path(kwargs["sidecar"])
        _make_pdf(out, pages=3)
        side.write_text("only first page", encoding="utf-8")

    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(),
        work_dir=tmp_path / "work",
        runner=runner,
        sanitizer=_copy_sanitizer,
    )
    result = adapter.ocr_pdf(str(src))
    assert [p.text for p in result.pages] == ["only first page", "", ""]


def test_ocrmypdf_adapter_sanitizes_before_runner_by_default(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf", pages=1)
    seen: dict[str, Any] = {"sanitized": False}

    def sanitizer(source: Path, cleaned: Path) -> None:
        seen["sanitized"] = True
        shutil.copyfile(source, cleaned)

    def runner(**kwargs: Any) -> None:
        in_path = Path(kwargs["input_file"])
        assert in_path.name.endswith(".clean.pdf")
        assert in_path.exists()
        out = Path(kwargs["output_file"])
        side = Path(kwargs["sidecar"])
        _make_pdf(out, pages=1)
        side.write_text("ok", encoding="utf-8")

    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(),
        work_dir=tmp_path / "work",
        runner=runner,
        sanitizer=sanitizer,
    )
    adapter.ocr_pdf(str(src))
    assert seen["sanitized"] is True


def test_ocrmypdf_adapter_can_disable_sanitize_via_setting(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "in.pdf", pages=1)
    seen: dict[str, Any] = {"sanitized": False}

    def sanitizer(_: Path, __: Path) -> None:
        seen["sanitized"] = True

    def runner(**kwargs: Any) -> None:
        assert Path(kwargs["input_file"]) == src
        out = Path(kwargs["output_file"])
        side = Path(kwargs["sidecar"])
        _make_pdf(out, pages=1)
        side.write_text("ok", encoding="utf-8")

    adapter = OcrmypdfAdapter(
        settings=OcrmypdfSettings(clean_before_ocr=False),
        work_dir=tmp_path / "work",
        runner=runner,
        sanitizer=sanitizer,
    )
    adapter.ocr_pdf(str(src))
    assert seen["sanitized"] is False
