"""Tests for the per-page feature extractors."""

from __future__ import annotations

from docunomnom.core.features import (
    detect_page_number_hint,
    find_keyword_hits,
    normalize_text,
)


def test_normalize_text_lowercases_and_collapses_whitespace() -> None:
    assert normalize_text("  Hello\tWorld\n") == "hello world"


def test_normalize_text_handles_nfkc_and_control_chars() -> None:
    # Fullwidth "I" -> NFKC "I"; embedded BEL is a control char -> space.
    raw = "Ｉｎｖｏｉｃｅ\x07#42"
    assert normalize_text(raw) == "invoice #42"


def test_normalize_empty_string() -> None:
    assert normalize_text("") == ""


def test_keyword_hits_top_of_page_scores_highest() -> None:
    text = "Invoice\n\nRest of the page text"
    hits = find_keyword_hits(text, page_no=1, keywords=("Invoice",))
    assert len(hits) == 1
    hit = hits[0]
    assert hit.keyword == "Invoice"
    assert hit.page_no == 1
    assert hit.score == 1.0
    assert "Invoice" in hit.snippet


def test_keyword_hits_late_in_page_scores_lower() -> None:
    pad = "x " * 200
    text = f"{pad} Invoice trailing"
    hits = find_keyword_hits(text, page_no=2, keywords=("Invoice",))
    assert len(hits) == 1
    assert hits[0].score == 0.5


def test_keyword_hits_dedupe_per_keyword() -> None:
    text = "Invoice\nMore invoice text mentioning invoice again"
    hits = find_keyword_hits(text, page_no=1, keywords=("Invoice", "Invoice"))
    assert len(hits) == 1


def test_keyword_hits_no_match() -> None:
    assert find_keyword_hits("some unrelated body", page_no=1, keywords=("Invoice",)) == []


def test_page_number_hint_detected_english() -> None:
    cue = detect_page_number_hint("Page 1 of 3", page_no=1)
    assert cue is not None
    assert cue.current == 1
    assert cue.total == 3
    assert cue.looks_like_document_start is True


def test_page_number_hint_detected_german() -> None:
    cue = detect_page_number_hint("Seite 2 von 5", page_no=2)
    assert cue is not None
    assert cue.current == 2 and cue.total == 5
    assert cue.looks_like_document_start is False


def test_page_number_hint_invalid_rejected() -> None:
    assert detect_page_number_hint("page 5 of 3", page_no=1) is None
    assert detect_page_number_hint("nothing here", page_no=1) is None
