"""Pure-Python PDF helpers used by Phase 2.

We rely on ``pypdf`` to keep the runtime dependency footprint small. The
heavy OCR work happens in the OCR adapters; this module only deals with the
already-OCR'd PDF (reading page count, splitting by page range) and with
parsing OCRmyPDF's sidecar text format.
"""

from __future__ import annotations

from pathlib import Path

# ``pypdf`` form-feed page separator used by OCRmyPDF's --sidecar output.
SIDECAR_PAGE_SEPARATOR = "\x0c"


class PdfReadError(RuntimeError):
    """Raised when the PDF cannot be read or is malformed."""


def pdf_page_count(path: str | Path) -> int:
    """Return the number of pages in ``path``."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except Exception as exc:  # pypdf raises various exceptions; normalize.
        raise PdfReadError(f"failed to read PDF page count: {exc}") from exc


def split_pdf_pages(
    source_path: str | Path,
    target_path: str | Path,
    *,
    start_page: int,
    end_page: int,
) -> None:
    """Write a new PDF containing pages ``start_page..end_page`` (1-indexed,
    inclusive) of ``source_path`` to ``target_path``.

    Page bounds are validated; out-of-range values raise ``PdfReadError``.
    """
    if start_page < 1 or end_page < start_page:
        raise PdfReadError(f"invalid page range: {start_page}..{end_page}")

    from pypdf import PdfReader, PdfWriter

    try:
        reader = PdfReader(str(source_path))
    except Exception as exc:
        raise PdfReadError(f"failed to open source PDF: {exc}") from exc

    total = len(reader.pages)
    if end_page > total:
        raise PdfReadError(f"end_page {end_page} exceeds source page count {total}")

    writer = PdfWriter()
    for idx in range(start_page - 1, end_page):
        writer.add_page(reader.pages[idx])

    with Path(target_path).open("wb") as out:
        writer.write(out)


def parse_sidecar_text(text: str, *, page_count: int) -> list[str]:
    """Parse an OCRmyPDF sidecar string into per-page text.

    The sidecar format separates pages with a form-feed (``\\x0c``). Some
    versions emit a trailing form-feed after the last page; we tolerate that
    and pad/truncate to ``page_count`` so downstream code can always rely on
    ``len(result) == page_count``.
    """
    parts = text.split(SIDECAR_PAGE_SEPARATOR)
    # Drop a trailing empty page caused by a terminal form-feed.
    if parts and parts[-1] == "":
        parts = parts[:-1]
    if len(parts) > page_count:
        parts = parts[:page_count]
    while len(parts) < page_count:
        parts.append("")
    return parts
