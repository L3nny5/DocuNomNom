"""Phase 5 tests for AI split adapters.

The adapters are tested against an in-process ``httpx`` mock transport so
no real network call is made. ``NoneAiSplitAdapter`` is tested directly.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from docunomnom.adapters.ai_split import (
    NoneAiSplitAdapter,
    OllamaAiSplitAdapter,
    OpenAiAiSplitAdapter,
)
from docunomnom.adapters.ai_split._schema import AiAdapterError, parse_ai_response
from docunomnom.config import NetworkSettings, OllamaSettings, OpenAISettings
from docunomnom.core.models import AiMode, AiProposalAction, EvidenceKind
from docunomnom.core.ports.ocr import OcrPageResult, OcrResult


def _ocr() -> OcrResult:
    return OcrResult(
        pages=(
            OcrPageResult(page_no=1, text="Invoice ACME services", layout={}),
            OcrPageResult(page_no=2, text="continuation", layout={}),
        ),
        artifact_path=None,
    )


def _proposal_payload() -> dict[str, Any]:
    return {
        "proposals": [
            {
                "action": "confirm",
                "start_page": 1,
                "end_page": 2,
                "confidence": 0.92,
                "reason_code": "keyword_invoice",
                "target_proposal_id": 0,
                "evidences": [
                    {
                        "kind": "keyword",
                        "page_no": 1,
                        "snippet": "Invoice",
                        "payload": {"keyword": "Invoice"},
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# none adapter
# ---------------------------------------------------------------------------


def test_none_adapter_returns_empty_tuple() -> None:
    adapter = NoneAiSplitAdapter()
    out = adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert out == ()


# ---------------------------------------------------------------------------
# parse_ai_response
# ---------------------------------------------------------------------------


def test_parse_ai_response_happy_path() -> None:
    proposals = parse_ai_response(json.dumps(_proposal_payload()))
    assert len(proposals) == 1
    p = proposals[0]
    assert p.action is AiProposalAction.CONFIRM
    assert p.evidences[0].kind is EvidenceKind.KEYWORD


def test_parse_ai_response_empty_text_returns_empty() -> None:
    assert parse_ai_response("") == ()


def test_parse_ai_response_rejects_non_json() -> None:
    with pytest.raises(AiAdapterError) as excinfo:
        parse_ai_response("not really json")
    assert excinfo.value.code == "ai_response_invalid"


def test_parse_ai_response_rejects_missing_action() -> None:
    payload = {"proposals": [{"start_page": 1, "end_page": 1, "confidence": 0.5}]}
    with pytest.raises(AiAdapterError):
        parse_ai_response(json.dumps(payload))


# ---------------------------------------------------------------------------
# Ollama adapter
# ---------------------------------------------------------------------------


def _ollama_handler(payload: dict[str, Any], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"]
        assert body["format"]
        assert body["stream"] is False
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def test_ollama_adapter_parses_structured_response() -> None:
    response = {"message": {"content": json.dumps(_proposal_payload())}}
    transport = _ollama_handler(response)
    client = httpx.Client(transport=transport)
    audited: list[tuple[str, dict[str, Any]]] = []
    adapter = OllamaAiSplitAdapter(
        settings=OllamaSettings(),
        client=client,
        audit_callback=lambda t, p: audited.append((t, p)),
    )
    proposals = adapter.propose(mode=AiMode.VALIDATE, existing_proposals=(), ocr=_ocr())
    assert len(proposals) == 1
    assert proposals[0].action is AiProposalAction.CONFIRM
    assert audited and audited[0][0] == "ai_called"
    assert audited[0][1]["proposal_count"] == 1
    adapter.close()


def test_ollama_adapter_off_mode_short_circuits() -> None:
    transport = httpx.MockTransport(
        lambda _r: pytest.fail("network must not be touched in OFF mode")
    )
    client = httpx.Client(transport=transport)
    adapter = OllamaAiSplitAdapter(settings=OllamaSettings(), client=client)
    out = adapter.propose(mode=AiMode.OFF, existing_proposals=(), ocr=_ocr())
    assert out == ()
    adapter.close()


def test_ollama_adapter_server_error_raises() -> None:
    transport = _ollama_handler({"error": "boom"}, status=503)
    client = httpx.Client(transport=transport)
    adapter = OllamaAiSplitAdapter(settings=OllamaSettings(), client=client)
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.VALIDATE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_server_error"
    adapter.close()


def test_ollama_adapter_loose_text_in_content_is_rejected() -> None:
    response = {"message": {"content": "definitely not JSON"}}
    transport = _ollama_handler(response)
    client = httpx.Client(transport=transport)
    adapter = OllamaAiSplitAdapter(settings=OllamaSettings(), client=client)
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.VALIDATE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_response_invalid"
    adapter.close()


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------


def _openai_handler(content: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer secret-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"]
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.MockTransport(handler)


def test_openai_adapter_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    transport = _openai_handler(json.dumps(_proposal_payload()))
    client = httpx.Client(transport=transport)
    adapter = OpenAiAiSplitAdapter(
        settings=OpenAISettings(),
        network=NetworkSettings(allow_external_egress=True),
        client=client,
    )
    proposals = adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert len(proposals) == 1
    adapter.close()


def test_openai_adapter_blocks_when_egress_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    transport = httpx.MockTransport(lambda _r: pytest.fail("network must be blocked"))
    client = httpx.Client(transport=transport)
    adapter = OpenAiAiSplitAdapter(
        settings=OpenAISettings(),
        network=NetworkSettings(allow_external_egress=False),
        client=client,
    )
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_egress_denied"
    adapter.close()


def test_openai_adapter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    transport = httpx.MockTransport(lambda _r: pytest.fail("network must be blocked"))
    client = httpx.Client(transport=transport)
    adapter = OpenAiAiSplitAdapter(
        settings=OpenAISettings(),
        network=NetworkSettings(allow_external_egress=True),
        client=client,
    )
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_auth_missing"
    adapter.close()


def test_openai_adapter_rejects_non_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    transport = httpx.MockTransport(lambda _r: pytest.fail("network must be blocked"))
    client = httpx.Client(transport=transport)
    adapter = OpenAiAiSplitAdapter(
        settings=OpenAISettings(base_url="http://api.openai.com"),
        network=NetworkSettings(allow_external_egress=True),
        client=client,
    )
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_config_invalid"
    adapter.close()


def test_openai_adapter_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "no"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenAiAiSplitAdapter(
        settings=OpenAISettings(),
        network=NetworkSettings(allow_external_egress=True),
        client=client,
    )
    with pytest.raises(AiAdapterError) as excinfo:
        adapter.propose(mode=AiMode.ENHANCE, existing_proposals=(), ocr=_ocr())
    assert excinfo.value.code == "ai_auth_failed"
    adapter.close()
