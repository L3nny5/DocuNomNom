"""PDF utilities (read page count, split by page range, parse OCR sidecar)."""

from .extract import (
    SIDECAR_PAGE_SEPARATOR,
    PdfReadError,
    parse_sidecar_text,
    pdf_page_count,
    split_pdf_pages,
)

__all__ = [
    "SIDECAR_PAGE_SEPARATOR",
    "PdfReadError",
    "parse_sidecar_text",
    "pdf_page_count",
    "split_pdf_pages",
]
