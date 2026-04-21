"""Lightweight layout / page-number cues.

Phase 2 stays deterministic and OCR-text-only — no PDF coordinate access.
The single cue we extract today is the "page X of N" / "Seite X von N"
pattern that is common at the top or bottom of multi-page documents. When
the running ``X`` resets to 1, that is a strong hint that a new document
begins on this page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Match e.g.  "Page 1 of 3", "Seite 1 / 5", "Page 2/5".  We accept both the
# English and German wording and a fairly permissive separator vocabulary.
_PAGE_NUMBER_RE = re.compile(
    r"(?:page|seite|pg\.)\s*(\d+)\s*(?:of|von|/|\-|—|–)\s*(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PageNumberHint:
    """Detected (current_page, total_pages) cue on a page."""

    page_no: int
    current: int
    total: int

    @property
    def looks_like_document_start(self) -> bool:
        """True iff this page advertises itself as ``1 of N``."""
        return self.current == 1 and self.total >= 1


def detect_page_number_hint(text: str, *, page_no: int) -> PageNumberHint | None:
    """Return the *first* page-number cue found in ``text``, or None."""
    if not text:
        return None
    match = _PAGE_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        current = int(match.group(1))
        total = int(match.group(2))
    except ValueError:
        return None
    if current < 1 or total < 1 or current > total:
        return None
    return PageNumberHint(page_no=page_no, current=current, total=total)
