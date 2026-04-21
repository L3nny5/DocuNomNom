"""AI split backend port.

Phase 1 only declares the interface plus the request/response shapes that the
Evidence Validator (Phase 5) will consume. Concrete adapters (none, ollama,
openai) and the validator itself are added in Phase 5.
"""

from __future__ import annotations

from typing import Protocol

from ..models.entities import AiProposalRequest, SplitProposal
from ..models.types import AiMode
from .ocr import OcrResult


class AiSplitPort(Protocol):
    def propose(
        self,
        *,
        mode: AiMode,
        existing_proposals: tuple[SplitProposal, ...],
        ocr: OcrResult,
    ) -> tuple[AiProposalRequest, ...]:
        """Return AI proposals for the given OCR analysis.

        The returned actions must respect the mode-specific whitelist
        (see plan §11). Each proposal must carry sufficient evidence; the
        Evidence Validator enforces that contract before persistence.
        """
        ...
