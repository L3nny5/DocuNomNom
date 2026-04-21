"""OpenAI AI split adapter.

Calls the OpenAI Chat Completions endpoint with
``response_format={"type": "json_object"}`` so the model emits a single
JSON object that we feed into :func:`parse_ai_response`. The API key is
read from the environment variable named in
``ai.openai.api_key_env`` — never persisted in YAML or DB.

Network egress is gated by ``network.allow_external_egress`` and (when
set) ``network.allowed_hosts`` so OpenAI calls cannot leak traffic from
an air-gapped deployment.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ...config import NetworkSettings, OpenAISettings
from ...core.models.entities import AiProposalRequest, SplitProposal
from ...core.models.types import AiMode
from ...core.ports.ocr import OcrResult
from ._schema import (
    SYSTEM_PROMPT,
    AiAdapterError,
    build_user_prompt,
    parse_ai_response,
)

logger = logging.getLogger(__name__)

AuditCallback = Callable[[str, dict[str, Any]], None]


class OpenAiAiSplitAdapter:
    """``AiSplitPort`` implementation backed by OpenAI's API."""

    def __init__(
        self,
        *,
        settings: OpenAISettings,
        network: NetworkSettings,
        client: httpx.Client | None = None,
        audit_callback: AuditCallback | None = None,
    ) -> None:
        self._settings = settings
        self._network = network
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
        self._validate_egress()

        api_key = os.environ.get(self._settings.api_key_env, "").strip()
        if not api_key:
            raise AiAdapterError(
                f"OpenAI API key missing in env {self._settings.api_key_env!r}",
                code="ai_auth_missing",
            )

        prompt = build_user_prompt(
            mode=mode,
            existing_proposals=existing_proposals,
            ocr=ocr,
        )
        body: dict[str, Any] = {
            "model": self._settings.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        url = urljoin(self._settings.base_url.rstrip("/") + "/", "v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(
                url,
                json=body,
                headers=headers,
                timeout=self._settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AiAdapterError(f"openai timeout: {exc}", code="ai_timeout") from exc
        except httpx.HTTPError as exc:
            raise AiAdapterError(f"openai transport error: {exc}", code="ai_transport") from exc

        if response.status_code == 401:
            raise AiAdapterError("openai unauthorized", code="ai_auth_failed")
        if response.status_code >= 500:
            raise AiAdapterError(
                f"openai server error: HTTP {response.status_code}",
                code="ai_server_error",
            )
        if response.status_code >= 400:
            raise AiAdapterError(
                f"openai client error: HTTP {response.status_code}",
                code="ai_client_error",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AiAdapterError(
                f"openai returned non-JSON envelope: {exc}",
                code="ai_response_invalid",
            ) from exc

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            raise AiAdapterError("openai response missing choices", code="ai_response_invalid")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise AiAdapterError("openai choice missing message", code="ai_response_invalid")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise AiAdapterError(
                "openai message.content must be a string",
                code="ai_response_invalid",
            )

        proposals = parse_ai_response(content)
        self._audit(
            "ai_called",
            {
                "backend": "openai",
                "model": self._settings.model,
                "mode": mode.value,
                "proposal_count": len(proposals),
                "existing_count": len(existing_proposals),
            },
        )
        return proposals

    def _validate_egress(self) -> None:
        parsed = urlparse(self._settings.base_url)
        if parsed.scheme != "https":
            raise AiAdapterError(
                f"openai base_url must be https (got scheme {parsed.scheme!r})",
                code="ai_config_invalid",
            )
        if not self._network.allow_external_egress:
            raise AiAdapterError(
                "openai call attempted but network.allow_external_egress is False",
                code="ai_egress_denied",
            )
        host = parsed.hostname or ""
        if self._network.allowed_hosts and host not in self._network.allowed_hosts:
            raise AiAdapterError(
                f"openai host {host!r} is not in network.allowed_hosts",
                code="ai_egress_denied",
            )


__all__ = ["OpenAiAiSplitAdapter"]
