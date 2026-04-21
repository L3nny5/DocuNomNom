"""Unit tests for ``derive_subparts_from_markers``."""

from __future__ import annotations

import pytest

from docunomnom.core.models import (
    DocumentPart,
    DocumentPartDecision,
    ReviewMarker,
    ReviewMarkerKind,
)
from docunomnom.core.usecases.review import (
    DerivedSubpart,
    InvalidMarkersError,
    derive_subparts_from_markers,
)


def _part(start: int, end: int) -> DocumentPart:
    return DocumentPart(
        id=1,
        analysis_id=1,
        start_page=start,
        end_page=end,
        decision=DocumentPartDecision.REVIEW_REQUIRED,
        confidence=0.5,
    )


def _start(page: int) -> ReviewMarker:
    return ReviewMarker(review_item_id=1, page_no=page, kind=ReviewMarkerKind.START)


def test_no_markers_returns_single_subpart_covering_whole_part() -> None:
    derived = derive_subparts_from_markers(_part(3, 7), [])
    assert derived == [DerivedSubpart(index=1, start_page=3, end_page=7)]


def test_explicit_marker_on_first_page_is_noop() -> None:
    derived = derive_subparts_from_markers(_part(1, 4), [_start(1)])
    assert derived == [DerivedSubpart(index=1, start_page=1, end_page=4)]


def test_single_interior_start_splits_into_two() -> None:
    derived = derive_subparts_from_markers(_part(1, 5), [_start(3)])
    assert derived == [
        DerivedSubpart(index=1, start_page=1, end_page=2),
        DerivedSubpart(index=2, start_page=3, end_page=5),
    ]


def test_multiple_starts_dedup_and_sort() -> None:
    derived = derive_subparts_from_markers(
        _part(1, 10),
        [_start(5), _start(3), _start(5), _start(8)],
    )
    assert derived == [
        DerivedSubpart(index=1, start_page=1, end_page=2),
        DerivedSubpart(index=2, start_page=3, end_page=4),
        DerivedSubpart(index=3, start_page=5, end_page=7),
        DerivedSubpart(index=4, start_page=8, end_page=10),
    ]


def test_reject_split_markers_are_ignored() -> None:
    rejected = ReviewMarker(review_item_id=1, page_no=3, kind=ReviewMarkerKind.REJECT_SPLIT)
    derived = derive_subparts_from_markers(_part(1, 5), [rejected])
    assert derived == [DerivedSubpart(index=1, start_page=1, end_page=5)]


def test_marker_below_range_raises() -> None:
    with pytest.raises(InvalidMarkersError):
        derive_subparts_from_markers(_part(3, 5), [_start(2)])


def test_marker_above_range_raises() -> None:
    with pytest.raises(InvalidMarkersError):
        derive_subparts_from_markers(_part(3, 5), [_start(6)])


def test_invalid_part_range_raises() -> None:
    bad = DocumentPart(
        id=1,
        analysis_id=1,
        start_page=5,
        end_page=4,
        decision=DocumentPartDecision.REVIEW_REQUIRED,
        confidence=0.5,
    )
    with pytest.raises(InvalidMarkersError):
        derive_subparts_from_markers(bad, [])
