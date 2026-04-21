"""Shared JSON schema + parser for AI split adapters.

The adapters always speak this exact JSON shape so the worker has a
single, tightly validated contract regardless of provider. Loose model
text never reaches the rest of the pipeline — :func:`parse_ai_response`
either returns a fully-typed list of ``AiProposalRequest`` or raises
:class:`AiAdapterError`.

Wire format (single object)
---------------------------

::

    {
      "proposals": [
        {
          "action": "confirm | reject | merge | adjust | add",
          "start_page": 1,
          "end_page": 3,
          "confidence": 0.82,
          "reason_code": "keyword_invoice_top_page",
          "target_proposal_id": 0,                  // omit / null for ``add``
          "evidences": [
            {
              "kind": "keyword | layout_break | sender_change |
                       page_number | structural | ocr_snippet",
              "page_no": 1,
              "snippet": "Invoice ACME ...",         // optional except for
                                                     // ocr_snippet
              "payload": {"keyword": "invoice"}
            }
          ]
        }
      ]
    }

Anything else (extra keys, missing required keys, wrong types) is
rejected at parse time. The Evidence Validator then runs the
mode-specific semantic gate downstream.
"""

from __future__ import annotations

import json
from typing import Any

from ...core.evidence.validator import allowed_actions_for_mode
from ...core.models.entities import AiEvidenceRequest, AiProposalRequest, SplitProposal
from ...core.models.types import AiMode, AiProposalAction, EvidenceKind
from ...core.ports.ocr import OcrResult


class AiAdapterError(RuntimeError):
    """Raised by AI split adapters on transport / parsing failures."""

    code: str

    def __init__(self, message: str, *, code: str = "ai_adapter_error") -> None:
        super().__init__(message)
        self.code = code


# JSON Schema we send to providers that support structured outputs.
JSON_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["proposals"],
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "action",
                    "start_page",
                    "end_page",
                    "confidence",
                    "reason_code",
                    "evidences",
                ],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [a.value for a in AiProposalAction],
                    },
                    "start_page": {"type": "integer", "minimum": 1},
                    "end_page": {"type": "integer", "minimum": 1},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "reason_code": {"type": "string", "maxLength": 64},
                    "target_proposal_id": {"type": ["integer", "null"], "minimum": 0},
                    "evidences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kind", "page_no"],
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": [k.value for k in EvidenceKind],
                                },
                                "page_no": {"type": "integer", "minimum": 1},
                                "snippet": {"type": ["string", "null"], "maxLength": 500},
                                "payload": {"type": "object"},
                            },
                        },
                    },
                },
            },
        }
    },
}


SYSTEM_PROMPT = (
    "You are a conservative document-splitting assistant. You must reply "
    "with a single JSON object matching the provided schema. Do not "
    "include any text outside the JSON object. Each proposal must cite "
    "concrete evidence (keyword hits, OCR snippets, layout signals, or "
    "page-number resets); do not invent boundaries without evidence."
)


def build_user_prompt(
    *,
    mode: AiMode,
    existing_proposals: tuple[SplitProposal, ...],
    ocr: OcrResult,
    page_text_max_chars: int = 1_500,
) -> str:
    """Render the user prompt with a strict allowed-actions list."""
    allowed = sorted(a.value for a in allowed_actions_for_mode(mode))
    page_lines: list[str] = []
    for page in ocr.pages:
        text = page.text.strip().replace("\n", " ")
        if len(text) > page_text_max_chars:
            text = text[: page_text_max_chars - 1] + "…"
        page_lines.append(f"page {page.page_no}: {text}")
    proposal_lines: list[str] = []
    for index, proposal in enumerate(existing_proposals):
        proposal_lines.append(
            f"[{index}] pages {proposal.start_page}..{proposal.end_page} "
            f"(reason={proposal.reason_code!r})"
        )

    sections = [
        f"Mode: {mode.value}",
        "Allowed actions: " + ", ".join(allowed),
        "Existing rule proposals (target_proposal_id refers to these indices):",
        *(proposal_lines or ["(none)"]),
        "Pages:",
        *(page_lines or ["(none)"]),
        "Reply with a JSON object matching the schema. If you have no "
        'evidence-backed action, return {"proposals": []}.',
    ]
    return "\n".join(sections)


def _coerce_str(value: Any) -> str:
    if not isinstance(value, str):
        raise AiAdapterError("expected string", code="ai_response_invalid")
    return value


def _coerce_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AiAdapterError(f"{field} must be an integer", code="ai_response_invalid")
    return int(value)


def _coerce_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise AiAdapterError(f"{field} must be numeric", code="ai_response_invalid")
    if not isinstance(value, int | float):
        raise AiAdapterError(f"{field} must be numeric", code="ai_response_invalid")
    return float(value)


def _parse_evidence(raw: Any) -> AiEvidenceRequest:
    if not isinstance(raw, dict):
        raise AiAdapterError("evidence must be an object", code="ai_response_invalid")
    try:
        kind = EvidenceKind(_coerce_str(raw["kind"]))
    except (KeyError, ValueError) as exc:
        raise AiAdapterError(f"invalid evidence kind: {exc}", code="ai_response_invalid") from exc
    page_no = _coerce_int(raw.get("page_no"), field="evidence.page_no")
    snippet_raw = raw.get("snippet")
    snippet: str | None
    snippet = None if snippet_raw is None else _coerce_str(snippet_raw)
    payload_raw = raw.get("payload", {})
    if not isinstance(payload_raw, dict):
        raise AiAdapterError("evidence.payload must be an object", code="ai_response_invalid")
    return AiEvidenceRequest(
        kind=kind,
        page_no=page_no,
        snippet=snippet,
        payload=dict(payload_raw),
    )


def _parse_proposal(raw: Any) -> AiProposalRequest:
    if not isinstance(raw, dict):
        raise AiAdapterError("proposal must be an object", code="ai_response_invalid")
    try:
        action = AiProposalAction(_coerce_str(raw["action"]))
    except (KeyError, ValueError) as exc:
        raise AiAdapterError(f"invalid action: {exc}", code="ai_response_invalid") from exc
    start_page = _coerce_int(raw.get("start_page"), field="start_page")
    end_page = _coerce_int(raw.get("end_page"), field="end_page")
    confidence = _coerce_float(raw.get("confidence"), field="confidence")
    reason_code = _coerce_str(raw.get("reason_code", ""))
    target_raw = raw.get("target_proposal_id")
    target: int | None
    target = None if target_raw is None else _coerce_int(target_raw, field="target_proposal_id")
    evidences_raw = raw.get("evidences", [])
    if not isinstance(evidences_raw, list):
        raise AiAdapterError("evidences must be a list", code="ai_response_invalid")
    evidences = tuple(_parse_evidence(e) for e in evidences_raw)
    return AiProposalRequest(
        action=action,
        start_page=start_page,
        end_page=end_page,
        confidence=confidence,
        reason_code=reason_code,
        evidences=evidences,
        target_proposal_id=target,
    )


def parse_ai_response(text: str) -> tuple[AiProposalRequest, ...]:
    """Parse a provider response into typed proposals.

    Adapters that obtain a string body call this. Empty / no-op responses
    are valid and produce an empty tuple.
    """
    if not text or not text.strip():
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AiAdapterError(f"non-JSON response: {exc}", code="ai_response_invalid") from exc
    if not isinstance(payload, dict):
        raise AiAdapterError("response root must be an object", code="ai_response_invalid")
    proposals_raw = payload.get("proposals", [])
    if not isinstance(proposals_raw, list):
        raise AiAdapterError("'proposals' must be a list", code="ai_response_invalid")
    return tuple(_parse_proposal(p) for p in proposals_raw)


__all__ = [
    "JSON_RESPONSE_SCHEMA",
    "SYSTEM_PROMPT",
    "AiAdapterError",
    "build_user_prompt",
    "parse_ai_response",
]
