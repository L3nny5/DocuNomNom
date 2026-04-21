"""Regression suite for known split edge cases (Phase 6).

These cases are the ones a v1 deployment is most likely to encounter
in the wild and that we want to keep stable across refactors. Every
case is a small, fixture-style construction of ``PageEvidence`` so it
stays readable next to its expectation.

Conservative-splitting property under test for every case:

* The splitter NEVER returns zero drafts when there is at least one
  page (always at least the whole-document fallback).
* Adjacent drafts NEVER overlap.
* The first draft starts at the first input page and the last draft
  ends at the last input page (no orphan pages).
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from docunomnom.core.features import KeywordHit, PageNumberHint
from docunomnom.core.rules import (
    PageEvidence,
    ProposalDraft,
    SplitterConfig,
    plan_splits,
)


def _ev(
    page_no: int,
    *,
    keyword: str | None = None,
    cue: tuple[int, int] | None = None,
) -> PageEvidence:
    hits: tuple[KeywordHit, ...] = ()
    if keyword is not None:
        hits = (
            KeywordHit(
                keyword=keyword,
                page_no=page_no,
                score=1.0,
                snippet=keyword,
            ),
        )
    cue_obj: PageNumberHint | None = None
    if cue is not None:
        cue_obj = PageNumberHint(page_no=page_no, current=cue[0], total=cue[1])
    return PageEvidence(page_no=page_no, keyword_hits=hits, page_number_hint=cue_obj)


def _assert_safety_invariants(
    pages: Iterable[PageEvidence],
    drafts: list[ProposalDraft],
) -> None:
    """Properties that MUST hold for every conservative split."""
    page_list = sorted(pages, key=lambda p: p.page_no)
    assert page_list, "fixture must have at least one page"
    assert drafts, "splitter must always return at least one draft"

    # Adjacent drafts: contiguous and non-overlapping.
    for left, right in zip(drafts, drafts[1:], strict=False):
        assert left.end_page < right.start_page, (
            f"drafts overlap or are unordered: {left} vs {right}"
        )
        assert right.start_page == left.end_page + 1, (
            f"drafts have a gap: {left.end_page} -> {right.start_page}"
        )

    # No orphan pages at the edges.
    assert drafts[0].start_page == page_list[0].page_no
    assert drafts[-1].end_page == page_list[-1].page_no


# ---------------------------------------------------------------------------
# Single-page documents
# ---------------------------------------------------------------------------


def test_single_page_no_keyword_yields_one_part() -> None:
    pages = [_ev(1)]
    drafts = plan_splits(pages, SplitterConfig())
    assert len(drafts) == 1
    assert (drafts[0].start_page, drafts[0].end_page) == (1, 1)
    _assert_safety_invariants(pages, drafts)


def test_single_page_with_keyword_yields_one_part() -> None:
    pages = [_ev(1, keyword="Invoice")]
    drafts = plan_splits(pages, SplitterConfig())
    assert len(drafts) == 1
    assert (drafts[0].start_page, drafts[0].end_page) == (1, 1)
    _assert_safety_invariants(pages, drafts)


# ---------------------------------------------------------------------------
# Boundary placement
# ---------------------------------------------------------------------------


def test_two_consecutive_invoices_split_into_two() -> None:
    """Two Invoice headers on adjacent pages -> exactly two parts."""
    pages = [
        _ev(1, keyword="Invoice"),
        _ev(2, keyword="Invoice"),
        _ev(3),
    ]
    drafts = plan_splits(pages, SplitterConfig())
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 1), (2, 3)]
    _assert_safety_invariants(pages, drafts)


def test_keyword_on_last_page_does_not_orphan_pages() -> None:
    """A keyword on the last page should still close the previous part
    cleanly and produce a one-page tail."""
    pages = [
        _ev(1, keyword="Invoice"),
        _ev(2),
        _ev(3),
        _ev(4, keyword="Vertrag"),
    ]
    drafts = plan_splits(pages, SplitterConfig())
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 3), (4, 4)]
    _assert_safety_invariants(pages, drafts)


def test_keyword_dense_burst_collapsed_by_min_pages() -> None:
    """Five keyword pages in a row with min_pages=2 should not produce
    five 1-page parts; we under-split conservatively."""
    pages = [_ev(i, keyword="Invoice") for i in range(1, 6)]
    drafts = plan_splits(pages, SplitterConfig(min_pages_per_part=2))
    # First part starts at 1; the next start has to wait two pages.
    starts = [(d.start_page, d.end_page) for d in drafts]
    assert starts[0][0] == 1
    assert starts[-1][1] == 5
    for left, right in zip(drafts, drafts[1:], strict=False):
        assert (right.start_page - left.start_page) >= 2
    _assert_safety_invariants(pages, drafts)


# ---------------------------------------------------------------------------
# Page-number cues
# ---------------------------------------------------------------------------


def test_page_number_reset_starts_new_document() -> None:
    pages = [
        _ev(1, keyword="Invoice"),
        _ev(2, cue=(1, 3)),
        _ev(3, cue=(2, 3)),
        _ev(4, cue=(3, 3)),
    ]
    drafts = plan_splits(pages, SplitterConfig())
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 1), (2, 4)]
    _assert_safety_invariants(pages, drafts)


def test_page_number_cue_without_reset_does_not_split() -> None:
    """Page-number cue ``2 of 3`` is not a document start."""
    pages = [
        _ev(1, keyword="Invoice"),
        _ev(2, cue=(2, 3)),
        _ev(3, cue=(3, 3)),
    ]
    drafts = plan_splits(pages, SplitterConfig())
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 3)]
    _assert_safety_invariants(pages, drafts)


# ---------------------------------------------------------------------------
# Pathological inputs
# ---------------------------------------------------------------------------


def test_unsorted_pages_are_normalized() -> None:
    pages = [
        _ev(3, keyword="Vertrag"),
        _ev(1, keyword="Invoice"),
        _ev(2),
    ]
    drafts = plan_splits(pages, SplitterConfig())
    assert [(d.start_page, d.end_page) for d in drafts] == [(1, 2), (3, 3)]
    _assert_safety_invariants(pages, drafts)


def test_no_evidence_falls_back_to_whole_document() -> None:
    pages = [_ev(i) for i in range(1, 6)]
    drafts = plan_splits(pages, SplitterConfig())
    assert len(drafts) == 1
    assert (drafts[0].start_page, drafts[0].end_page) == (1, 5)
    _assert_safety_invariants(pages, drafts)


@pytest.mark.parametrize(
    ("min_pages", "expected"),
    [
        (1, [(1, 1), (2, 2), (3, 3)]),
        (2, [(1, 2), (3, 3)]),
        (5, [(1, 3)]),
    ],
)
def test_min_pages_per_part_under_splits_predictably(
    min_pages: int, expected: list[tuple[int, int]]
) -> None:
    pages = [
        _ev(1, keyword="Invoice"),
        _ev(2, keyword="Invoice"),
        _ev(3, keyword="Invoice"),
    ]
    drafts = plan_splits(pages, SplitterConfig(min_pages_per_part=min_pages))
    assert [(d.start_page, d.end_page) for d in drafts] == expected
    _assert_safety_invariants(pages, drafts)
