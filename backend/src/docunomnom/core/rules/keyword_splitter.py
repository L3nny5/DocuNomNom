"""Conservative rule-based splitter.

The splitter looks at per-page evidence and decides where new documents
*start*. Boundaries are intentionally conservative — we prefer to under-split
(leave two adjacent documents glued together) over to over-split (cut a
single document into pieces).

Inputs are domain primitives from ``core.features``; the splitter knows
nothing about OCR, AI, or persistence — it operates on already-extracted
features only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..features.keyword import KeywordHit
from ..features.layout import PageNumberHint


@dataclass(frozen=True, slots=True)
class PageEvidence:
    """All deterministic evidence for a single page."""

    page_no: int
    keyword_hits: tuple[KeywordHit, ...] = ()
    page_number_hint: PageNumberHint | None = None


@dataclass(frozen=True, slots=True)
class SplitterConfig:
    """Configuration knobs for the rule splitter."""

    min_pages_per_part: int = 1


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    """A rule-only candidate split, before persistence.

    The splitter does not assign a final ``confidence`` — that is the job of
    the confidence aggregator. We *do* expose the per-evidence subscores so
    the aggregator can combine them with configurable weights.
    """

    start_page: int
    end_page: int
    keyword_hit: KeywordHit | None = None
    page_number_hint: PageNumberHint | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def _find_start_pages(
    pages: list[PageEvidence],
    config: SplitterConfig,
) -> list[tuple[int, ProposalDraft]]:
    """Return (start_page, draft-skeleton) for every page that begins a new
    document. The first page always begins a document by definition."""
    starts: list[tuple[int, ProposalDraft]] = []
    last_start = 0
    for page in pages:
        # A page starts a new document if any of these is true:
        #   1) It is the very first page of the file.
        #   2) It contains a keyword hit (any score >= 0.5 by construction).
        #   3) Its page-number cue says "1 of N".
        keyword = page.keyword_hits[0] if page.keyword_hits else None
        cue = page.page_number_hint if page.page_number_hint else None

        if page.page_no == 1:
            reason_codes: list[str] = ["first_page"]
            if keyword is not None:
                reason_codes.append("keyword_hit")
            if cue is not None and cue.looks_like_document_start:
                reason_codes.append("page_number_cue")
            starts.append(
                (
                    page.page_no,
                    ProposalDraft(
                        start_page=page.page_no,
                        end_page=page.page_no,
                        keyword_hit=keyword,
                        page_number_hint=cue,
                        reason_codes=tuple(reason_codes),
                    ),
                )
            )
            last_start = page.page_no
            continue

        is_start = keyword is not None or (cue is not None and cue.looks_like_document_start)
        if not is_start:
            continue

        # Conservative: enforce min_pages_per_part since the previous start.
        if (page.page_no - last_start) < config.min_pages_per_part:
            continue

        reason_codes = []
        if keyword is not None:
            reason_codes.append("keyword_hit")
        if cue is not None and cue.looks_like_document_start:
            reason_codes.append("page_number_cue")
        starts.append(
            (
                page.page_no,
                ProposalDraft(
                    start_page=page.page_no,
                    end_page=page.page_no,
                    keyword_hit=keyword,
                    page_number_hint=cue,
                    reason_codes=tuple(reason_codes),
                ),
            )
        )
        last_start = page.page_no
    return starts


def plan_splits(
    pages: list[PageEvidence],
    config: SplitterConfig,
) -> list[ProposalDraft]:
    """Compute proposal drafts for the given page evidence.

    Always returns at least one draft (covering the whole document) when
    ``pages`` is non-empty.
    """
    if not pages:
        return []
    pages = sorted(pages, key=lambda p: p.page_no)
    last_page_no = pages[-1].page_no
    starts = _find_start_pages(pages, config)
    if not starts:
        # Defensive: synthesise the whole-document draft.
        starts = [
            (
                pages[0].page_no,
                ProposalDraft(
                    start_page=pages[0].page_no,
                    end_page=pages[0].page_no,
                    reason_codes=("first_page",),
                ),
            )
        ]

    drafts: list[ProposalDraft] = []
    for idx, (start, skel) in enumerate(starts):
        end = (starts[idx + 1][0] - 1) if idx + 1 < len(starts) else last_page_no
        drafts.append(
            ProposalDraft(
                start_page=start,
                end_page=end,
                keyword_hit=skel.keyword_hit,
                page_number_hint=skel.page_number_hint,
                reason_codes=skel.reason_codes,
            )
        )
    return drafts
