"""Tests for the generic external OCR API adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pypdf import PdfWriter

from docunomnom.adapters.ocr import (
    GenericExternalOcrAdapter,
    OcrConfigError,
    OcrEgressDeniedError,
    OcrServerError,
    OcrTimeoutError,
)
from docunomnom.config import ExternalOcrApiSettings, NetworkSettings


def _make_pdf(path: Path, *, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _ok_response(pages: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps({"pages": pages}).encode("utf-8"))


def _api(**overrides: Any) -> ExternalOcrApiSettings:
    base: dict[str, Any] = dict(
        endpoint="https://ocr.example.com/v1/ocr",
        timeout_seconds=5.0,
        max_retries=2,
        backoff_base_seconds=0.0,
        backoff_max_seconds=0.0,
        max_payload_mb=10.0,
        page_chunk_size=10,
        require_https=True,
    )
    base.update(overrides)
    return ExternalOcrApiSettings(**base)


def _net(**overrides: Any) -> NetworkSettings:
    base: dict[str, Any] = dict(allow_external_egress=True, allowed_hosts=())
    base.update(overrides)
    return NetworkSettings(**base)


def test_egress_denied_when_disabled(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf")
    adapter = GenericExternalOcrAdapter(
        api=_api(),
        network=NetworkSettings(allow_external_egress=False),
        work_dir=tmp_path / "work",
    )
    with pytest.raises(OcrEgressDeniedError):
        adapter.ocr_pdf(str(pdf))


def test_https_required(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf")
    adapter = GenericExternalOcrAdapter(
        api=_api(endpoint="http://insecure.example.com/ocr"),
        network=_net(),
        work_dir=tmp_path / "work",
    )
    with pytest.raises(OcrConfigError):
        adapter.ocr_pdf(str(pdf))


def test_host_not_in_allowlist_rejected(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf")
    adapter = GenericExternalOcrAdapter(
        api=_api(),
        network=_net(allowed_hosts=("only.example.org",)),
        work_dir=tmp_path / "work",
    )
    with pytest.raises(OcrEgressDeniedError):
        adapter.ocr_pdf(str(pdf))


def test_happy_path_emits_audit(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)
    audits: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response([{"page_no": 1, "text": "extracted text"}])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = GenericExternalOcrAdapter(
        api=_api(),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        audit_callback=lambda t, p: audits.append((t, p)),
    )
    result = adapter.ocr_pdf(str(pdf), languages=("eng",))

    assert [p.text for p in result.pages] == ["extracted text"]
    assert any(t == "external_ocr_call" and p["status"] == "ok" for t, p in audits)
    # Audit payload must NOT contain document content.
    for _t, payload in audits:
        for value in payload.values():
            assert not (isinstance(value, str) and "extracted text" in value)


def test_retries_on_5xx_then_succeeds(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, text="upstream down")
        return _ok_response([{"page_no": 1, "text": "ok"}])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = GenericExternalOcrAdapter(
        api=_api(max_retries=3, backoff_base_seconds=0.5, backoff_max_seconds=2.0),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        sleep=sleeps.append,
    )
    result = adapter.ocr_pdf(str(pdf))

    assert calls["n"] == 2
    assert result.pages[0].text == "ok"
    assert sleeps == [0.5]  # one backoff before the second attempt


def test_5xx_exhausts_retries_and_raises(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = GenericExternalOcrAdapter(
        api=_api(max_retries=1, backoff_base_seconds=0.0),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        sleep=lambda _s: None,
    )
    with pytest.raises(OcrServerError):
        adapter.ocr_pdf(str(pdf))


def test_4xx_not_retried(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = GenericExternalOcrAdapter(
        api=_api(max_retries=5, backoff_base_seconds=0.0),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        sleep=lambda _s: None,
    )
    from docunomnom.adapters.ocr import OcrAdapterError

    with pytest.raises(OcrAdapterError):
        adapter.ocr_pdf(str(pdf))
    assert calls["n"] == 1


def test_timeout_classified(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = GenericExternalOcrAdapter(
        api=_api(max_retries=0),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        sleep=lambda _s: None,
    )
    with pytest.raises(OcrTimeoutError):
        adapter.ocr_pdf(str(pdf))


def test_chunking_when_page_count_exceeds_chunk_size(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "big.pdf", pages=4)
    seen_ranges: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ranges.append(1)
        return _ok_response(
            [
                {"page_no": 1, "text": "a"},
                {"page_no": 2, "text": "b"},
            ]
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    adapter = GenericExternalOcrAdapter(
        api=_api(page_chunk_size=2),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        sleep=lambda _s: None,
    )
    result = adapter.ocr_pdf(str(pdf))

    # 4 pages / chunk_size 2 → 2 calls.
    assert len(seen_ranges) == 2
    # Page numbers reindexed into the global page space.
    assert [p.page_no for p in result.pages] == [1, 2, 3, 4]


def test_audit_payload_does_not_include_text(tmp_path: Path) -> None:
    """Stronger version: walk the entire payload tree and assert no 'text' key."""
    pdf = _make_pdf(tmp_path / "in.pdf", pages=1)
    audits: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response([{"page_no": 1, "text": "secret content"}])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    adapter = GenericExternalOcrAdapter(
        api=_api(),
        network=_net(),
        work_dir=tmp_path / "work",
        client=client,
        audit_callback=lambda t, p: audits.append((t, p)),
    )
    adapter.ocr_pdf(str(pdf))

    for _t, payload in audits:
        assert "text" not in payload
        assert "secret content" not in json.dumps(payload)
