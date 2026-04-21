"""``none`` AI split adapter.

Returns no proposals for any input. Used when ``ai.backend=none`` so the
worker can keep the adapter call site uniform without branching at every
stage.
"""

from __future__ import annotations

from ...core.models.entities import AiProposalRequest, SplitProposal
from ...core.models.types import AiMode
from ...core.ports.ocr import OcrResult


class NoneAiSplitAdapter:
    """``AiSplitPort`` implementation that always returns ``()``."""

    def propose(
        self,
        *,
        mode: AiMode,
        existing_proposals: tuple[SplitProposal, ...],
        ocr: OcrResult,
    ) -> tuple[AiProposalRequest, ...]:
        del mode, existing_proposals, ocr
        return ()


__all__ = ["NoneAiSplitAdapter"]
