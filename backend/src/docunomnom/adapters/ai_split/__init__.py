"""AI split adapters (Phase 5).

Three concrete adapters implement ``AiSplitPort``:

* :class:`NoneAiSplitAdapter` — no-op, used when ``ai.backend=none``.
* :class:`OllamaAiSplitAdapter` — Ollama HTTP backend.
* :class:`OpenAiAiSplitAdapter` — OpenAI HTTP backend.

All AI-produced proposals must pass through the Evidence Validator
(``docunomnom.core.evidence``) before reaching the Confidence Aggregator.
"""

from ._schema import (
    JSON_RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    AiAdapterError,
    build_user_prompt,
    parse_ai_response,
)
from .none import NoneAiSplitAdapter
from .ollama import OllamaAiSplitAdapter
from .openai import OpenAiAiSplitAdapter

__all__ = [
    "JSON_RESPONSE_SCHEMA",
    "SYSTEM_PROMPT",
    "AiAdapterError",
    "NoneAiSplitAdapter",
    "OllamaAiSplitAdapter",
    "OpenAiAiSplitAdapter",
    "build_user_prompt",
    "parse_ai_response",
]
