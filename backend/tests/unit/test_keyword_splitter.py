"""Tests for the rule-based keyword splitter."""

from __future__ import annotations

from docunomnom.core.features import KeywordHit, PageNumberHint
from docunomnom.core.rules import (
    PageEvidence,
    SplitterConfig,
    plan_splits,
)


def _ev(
    page_no: int,
    *,
    keyword: str | None = None,
    score: float = 1.0,
    cue: tuple[int, int] | None = None,
) -> PageEvidence:
    hits: tuple[KeywordHit, ...] = ()
    if keyword is not None:
        hits = (
            KeywordHit(
                keyword=keyword,
                page_no=page_no,
                score=score,
                snippet=keyword,
            ),
        )
    cue_obj: PageNumberHint | None = None
    if cue is not None:
        cue_obj = PageNumberHint(page_no=page_no, current=cue[0], total=cue[1])
    return PageEvidence(page_no=page_no, keyword_hits=hits, page_number_hint=cue_obj)


def test_empty_pages_returns_no_drafts() -> None:
    assert plan_splits([], SplitterConfig()) == []


def test_single_keyword_only_first_page() -> None:
    drafts = plan_splits(
        [
            _ev(1, keyword="Invoice"),
            _ev(2),
            _ev(3),
        ],
        SplitterConfig(),
    )
    assert len(drafts) == 1
    assert drafts[0].start_page == 1 and drafts[0].end_page == 3
    assert "first_page" in drafts[0].reason_codes
    assert "keyword_hit" in drafts[0].reason_codes


def test_two_documents_split_by_keyword_on_page_3() -> None:
    drafts = plan_splits(
        [
            _ev(1, keyword="Invoice"),
            _ev(2),
            _ev(3, keyword="Vertrag"),
            _ev(4),
        ],
        SplitterConfig(),
    )
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 2), (3, 4)]


def test_page_number_cue_one_of_n_starts_new_document() -> None:
    drafts = plan_splits(
        [
            _ev(1, keyword="Invoice"),
            _ev(2, cue=(1, 2)),
            _ev(3, cue=(2, 2)),
        ],
        SplitterConfig(),
    )
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 1), (2, 3)]


def test_min_pages_per_part_under_splits_when_too_close() -> None:
    drafts = plan_splits(
        [
            _ev(1, keyword="Invoice"),
            _ev(2, keyword="Vertrag"),  # rejected, would yield a 1-page first part
        ],
        SplitterConfig(min_pages_per_part=2),
    )
    assert len(drafts) == 1
    assert drafts[0].start_page == 1 and drafts[0].end_page == 2


def test_no_evidence_falls_back_to_whole_document() -> None:
    drafts = plan_splits(
        [_ev(1), _ev(2), _ev(3)],
        SplitterConfig(),
    )
    assert len(drafts) == 1
    assert drafts[0].start_page == 1 and drafts[0].end_page == 3
    assert "first_page" in drafts[0].reason_codes
