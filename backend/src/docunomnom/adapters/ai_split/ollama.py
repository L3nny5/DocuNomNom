"""Ollama AI split adapter.

Calls Ollama's ``/api/chat`` endpoint with ``format=json`` so the model
is forced to emit a single JSON object. The response body's ``message.content``
is the JSON payload we feed to :func:`parse_ai_response`.

Ollama is treated as part of the local network: this adapter does
**not** consult ``network.allow_external_egress`` (that flag governs
external-internet egress, e.g. OpenAI/external OCR APIs). Operators
deploy Ollama themselves; locking the model down is their responsibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin

import httpx

from ...config import OllamaSettings
from ...core.models.entities import AiProposalRequest, SplitProposal
from ...core.models.types import AiMode
from ...core.ports.ocr import OcrResult
from ._schema import (
    JSON_RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    AiAdapterError,
    build_user_prompt,
    parse_ai_response,
)

logger = logging.getLogger(__name__)

AuditCallback = Callable[[str, dict[str, Any]], None]


class OllamaAiSplitAdapter:
    """``AiSplitPort`` implementation backed by an Ollama server."""

    def __init__(
        self,
        *,
        settings: OllamaSettings,
        client: httpx.Client | None = None,
        audit_callback: AuditCallback | None = None,
    ) -> None:
        self._settings = settings
        self._client_supplied = client is not None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._audit = audit_callback or (lambda _t, _p: None)

    def close(self) -> None:
        if not self._client_supplied:
            self._client.close()

    def propose(
        self,
        *,
        mode: AiMode,
        existing_proposals: tuple[SplitProposal, ...],
        ocr: OcrResult,
    ) -> tuple[AiProposalRequest, ...]:
        if mode is AiMode.OFF:
            return ()
        prompt = build_user_prompt(
            mode=mode,
            existing_proposals=existing_proposals,
            ocr=ocr,
        )
        body = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": JSON_RESPONSE_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        url = urljoin(self._settings.base_url.rstrip("/") + "/", "api/chat")
        try:
            response = self._client.post(
                url,
                json=body,
                timeout=self._settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AiAdapterError(f"ollama timeout: {exc}", code="ai_timeout") from exc
        except httpx.HTTPError as exc:
            raise AiAdapterError(f"ollama transport error: {exc}", code="ai_transport") from exc

        if response.status_code >= 500:
            raise AiAdapterError(
                f"ollama server error: HTTP {response.status_code}",
                code="ai_server_error",
            )
        if response.status_code >= 400:
            raise AiAdapterError(
                f"ollama client error: HTTP {response.status_code}",
                code="ai_client_error",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AiAdapterError(
                f"ollama returned non-JSON envelope: {exc}",
                code="ai_response_invalid",
            ) from exc

        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            raise AiAdapterError("ollama response missing 'message'", code="ai_response_invalid")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise AiAdapterError(
                "ollama 'message.content' must be a string",
                code="ai_response_invalid",
            )

        proposals = parse_ai_response(content)
        self._audit(
            "ai_called",
            {
                "backend": "ollama",
                "model": self._settings.model,
                "mode": mode.value,
                "proposal_count": len(proposals),
                "existing_count": len(existing_proposals),
            },
        )
        return proposals


__all__ = ["OllamaAiSplitAdapter"]
