"""Default ``AiSplitPort`` factory for the worker (Phase 5).

Wraps the three Phase 5 adapters and dispatches based on ``ai.backend``.
Kept separate from ``processor.py`` so tests can inject a fake adapter
without exercising the real provider clients.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..adapters.ai_split import (
    NoneAiSplitAdapter,
    OllamaAiSplitAdapter,
    OpenAiAiSplitAdapter,
)
from ..config import Settings
from ..core.models import AiBackend
from ..core.ports.ai_split import AiSplitPort

AuditCb = Callable[[str, dict[str, Any]], None]


def build_ai_split_port_factory(
    settings: Settings,
) -> Callable[[AuditCb], AiSplitPort]:
    """Return ``(audit_cb) -> AiSplitPort`` for the configured backend.

    The chosen backend is fixed for the lifetime of the worker process.
    """

    def factory(audit_cb: AuditCb) -> AiSplitPort:
        backend = settings.ai.backend
        if backend is AiBackend.NONE:
            return NoneAiSplitAdapter()
        if backend is AiBackend.OLLAMA:
            return OllamaAiSplitAdapter(
                settings=settings.ai.ollama,
                audit_callback=audit_cb,
            )
        if backend is AiBackend.OPENAI:
            return OpenAiAiSplitAdapter(
                settings=settings.ai.openai,
                network=settings.network,
                audit_callback=audit_cb,
            )
        raise ValueError(f"unsupported AI backend: {backend!r}")

    return factory


__all__ = ["build_ai_split_port_factory"]
