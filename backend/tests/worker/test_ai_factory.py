"""Phase 5 tests for ``build_ai_split_port_factory``."""

from __future__ import annotations

from docunomnom.adapters.ai_split import (
    NoneAiSplitAdapter,
    OllamaAiSplitAdapter,
    OpenAiAiSplitAdapter,
)
from docunomnom.config import AiSettings
from docunomnom.config.settings import Settings
from docunomnom.core.models import AiBackend, AiMode
from docunomnom.worker.ai_factory import build_ai_split_port_factory


def _audit(_t: str, _p: dict[str, object]) -> None:
    return None


def test_factory_picks_none_adapter_by_default() -> None:
    settings = Settings(ai=AiSettings(backend=AiBackend.NONE, mode=AiMode.OFF))
    adapter = build_ai_split_port_factory(settings)(_audit)
    assert isinstance(adapter, NoneAiSplitAdapter)


def test_factory_builds_ollama_adapter() -> None:
    settings = Settings(ai=AiSettings(backend=AiBackend.OLLAMA, mode=AiMode.VALIDATE))
    adapter = build_ai_split_port_factory(settings)(_audit)
    assert isinstance(adapter, OllamaAiSplitAdapter)
    adapter.close()


def test_factory_builds_openai_adapter() -> None:
    settings = Settings(ai=AiSettings(backend=AiBackend.OPENAI, mode=AiMode.VALIDATE))
    adapter = build_ai_split_port_factory(settings)(_audit)
    assert isinstance(adapter, OpenAiAiSplitAdapter)
    adapter.close()
