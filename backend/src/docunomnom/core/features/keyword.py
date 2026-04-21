"""Keyword feature extraction.

Returns the matched keyword, its location in the *original* text (for
later snippet building), and a ``score`` in [0, 1]. The score is
intentionally simple at v1: 1.0 if the match is in the first half of the
page, scaled linearly down to 0.5 if it is in the last 25%. The intuition is
that document boundaries usually appear near the top of a page; matches in
the body are weaker evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .text import normalize_text


@dataclass(frozen=True, slots=True)
class KeywordHit:
    keyword: str
    page_no: int
    score: float
    snippet: str


def _build_snippet(original: str, position: int, length: int, *, radius: int = 60) -> str:
    """Return a short context window around ``position`` in ``original``."""
    if not original:
        return ""
    start = max(0, position - radius)
    end = min(len(original), position + length + radius)
    snippet = original[start:end].strip()
    return " ".join(snippet.split())


def find_keyword_hits(
    text: str,
    *,
    page_no: int,
    keywords: Iterable[str],
) -> list[KeywordHit]:
    """Return one hit per (page, keyword) pair found in ``text``.

    The first occurrence of each keyword wins so we don't double-count.
    """
    if not text:
        return []
    normalized = normalize_text(text)
    if not normalized:
        return []
    page_length = len(normalized)
    hits: list[KeywordHit] = []
    seen: set[str] = set()
    for raw_kw in keywords:
        kw = normalize_text(raw_kw)
        if not kw or kw in seen:
            continue
        idx = normalized.find(kw)
        if idx < 0:
            continue
        seen.add(kw)
        # Position-driven score: top of page is strongest evidence.
        rel = idx / max(1, page_length)
        if rel <= 0.5:
            score = 1.0
        elif rel <= 0.75:
            score = 0.75
        else:
            score = 0.5
        snippet = _build_snippet(text, idx, len(kw))
        hits.append(
            KeywordHit(
                keyword=raw_kw,
                page_no=page_no,
                score=score,
                snippet=snippet,
            )
        )
    return hits
