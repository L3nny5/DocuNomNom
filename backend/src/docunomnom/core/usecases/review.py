"""Phase 4 review-workflow primitives.

This module is intentionally framework-free: it contains the pure logic
that turns a manual marker set into a deterministic list of sub-parts
for a reviewed ``DocumentPart``. Persistence, PDF I/O, and HTTP wiring
live in adapter/API layers.

Marker semantics (Phase 4):

- A ``START`` marker on page ``p`` means "a new sub-document begins here".
- The very first page of the original part is *implicitly* a start; any
  explicit ``START`` marker on that page is a no-op.
- ``REJECT_SPLIT`` markers are accepted by the persistence layer (so the
  schema stays stable for Phase 5) but the deterministic finalize logic
  ignores them — the reviewer expresses the reviewed split layout solely
  through ``START`` markers in v1.

Failure mode: any marker outside the original part's page range is a
caller error and surfaces as ``InvalidMarkersError`` so the API can
return 4xx instead of inventing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.entities import DocumentPart, ReviewMarker
from ..models.types import ReviewMarkerKind


class InvalidMarkersError(ValueError):
    """Raised when a marker set cannot be applied to a part."""


@dataclass(frozen=True, slots=True)
class DerivedSubpart:
    """A planned sub-part derived from the marker set.

    ``index`` is 1-based to match the export naming convention used by
    the Phase 2 exporter.
    """

    index: int
    start_page: int
    end_page: int


def derive_subparts_from_markers(
    part: DocumentPart,
    markers: list[ReviewMarker],
) -> list[DerivedSubpart]:
    """Project ``markers`` onto ``part`` and return the resulting sub-parts.

    Rules (deliberately conservative):

    1. Only ``START`` markers participate in the derivation.
    2. Each start page in the (deduped, in-range) set begins a sub-part.
    3. The implicit first start at ``part.start_page`` is always present.
    4. Each sub-part runs up to (but not including) the next start, and
       the last sub-part runs to ``part.end_page``.

    With zero ``START`` markers (or only one on ``part.start_page``), the
    result is a single sub-part covering the entire part — the explicit
    "no split" outcome of the review.
    """
    if part.start_page < 1 or part.end_page < part.start_page:
        raise InvalidMarkersError(f"part has invalid page range {part.start_page}..{part.end_page}")

    starts: set[int] = {part.start_page}
    for marker in markers:
        if marker.kind is not ReviewMarkerKind.START:
            continue
        if marker.page_no < part.start_page or marker.page_no > part.end_page:
            raise InvalidMarkersError(
                f"marker page {marker.page_no} outside part range "
                f"{part.start_page}..{part.end_page}"
            )
        starts.add(marker.page_no)

    ordered = sorted(starts)
    sub_parts: list[DerivedSubpart] = []
    for idx, start in enumerate(ordered, start=1):
        end = ordered[idx] - 1 if idx < len(ordered) else part.end_page
        sub_parts.append(DerivedSubpart(index=idx, start_page=start, end_page=end))
    return sub_parts


__all__ = [
    "DerivedSubpart",
    "InvalidMarkersError",
    "derive_subparts_from_markers",
]
