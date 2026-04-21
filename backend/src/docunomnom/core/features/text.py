"""Text normalization used by all feature extractors.

The goal is to make matching robust against OCR noise and locale differences
*without* destroying signal: lowercasing, NFKC normalization, whitespace
collapsing, and stripping zero-width / control characters.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f]")


def normalize_text(text: str) -> str:
    """Return a canonical form of ``text`` suitable for keyword matching."""
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text)
    no_ctrl = _CTRL_RE.sub(" ", nfkc)
    lowered = no_ctrl.casefold()
    collapsed = _WHITESPACE_RE.sub(" ", lowered).strip()
    return collapsed
