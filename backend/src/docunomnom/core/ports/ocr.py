"""OCR backend port.

Phase 1 only declares the interface and the normalized result shape. Concrete
adapters (OCRmyPDF, Generic External API) are added in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class OcrPageResult:
    """OCR result for a single page in the normalized shape."""

    page_no: int
    text: str
    layout: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Normalized OCR output for a whole PDF."""

    pages: tuple[OcrPageResult, ...]
    artifact_path: str | None = None


class OcrPort(Protocol):
    def ocr_pdf(
        self,
        source_path: str,
        *,
        languages: tuple[str, ...] = ("eng", "deu"),
    ) -> OcrResult:
        """Run OCR on the given PDF and return the normalized result."""
        ...
