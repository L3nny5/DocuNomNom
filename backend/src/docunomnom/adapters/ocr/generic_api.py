"""Generic external OCR API adapter.

The adapter speaks one canonical request/response shape so we don't pin
ourselves to any single provider in v1. Provider-specific adapters can wrap
this contract in later phases.

Canonical wire format
---------------------

Request (multipart POST to ``{endpoint}``):

* ``file``    : the PDF bytes
* ``languages``: comma-separated list (``"eng,deu"``)

Response (JSON):

::

    {
      "pages": [
        {"page_no": 1, "text": "…", "layout": {...optional...}},
        ...
      ],
      "artifact_url": "https://…"   // optional, ignored by Phase 2
    }

Safety controls
---------------

* HTTPS-only by default (``require_https=True``).
* External egress denied unless ``network.allow_external_egress`` is True.
* Host must be on the allowlist (``network.allowed_hosts``) when set.
* Strict timeout per attempt and a capped exponential backoff retry policy.
* PDF size checked against ``max_payload_mb`` before the call.
* Page chunking is implemented so large PDFs can be split into several
  smaller calls instead of one oversized request.
* Audit events are emitted via the supplied callback (see
  ``audit_callback``) without ever including document contents.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ...config import ExternalOcrApiSettings, NetworkSettings
from ...core.ports.ocr import OcrPageResult, OcrResult
from ..pdf import pdf_page_count, split_pdf_pages
from .errors import (
    OcrAdapterError,
    OcrConfigError,
    OcrEgressDeniedError,
    OcrPayloadTooLargeError,
    OcrServerError,
    OcrTimeoutError,
    OcrTransportError,
)

logger = logging.getLogger(__name__)


AuditCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class _Attempt:
    number: int
    sleep_before_seconds: float


def _retry_schedule(*, max_retries: int, base: float, cap: float) -> list[_Attempt]:
    """Return one entry per attempt (1..max_retries+1)."""
    out: list[_Attempt] = [_Attempt(number=1, sleep_before_seconds=0.0)]
    for n in range(1, max_retries + 1):
        delay = min(cap, base * (2 ** (n - 1)))
        out.append(_Attempt(number=n + 1, sleep_before_seconds=delay))
    return out


class GenericExternalOcrAdapter:
    """``OcrPort`` implementation against a generic external OCR API."""

    def __init__(
        self,
        *,
        api: ExternalOcrApiSettings,
        network: NetworkSettings,
        work_dir: Path,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        audit_callback: AuditCallback | None = None,
    ) -> None:
        self._api = api
        self._network = network
        self._work_dir = work_dir
        self._client_supplied = client is not None
        self._client = client or httpx.Client(timeout=api.timeout_seconds)
        self._sleep = sleep
        self._audit = audit_callback or (lambda _t, _p: None)

    def close(self) -> None:
        if not self._client_supplied:
            self._client.close()

    # ----------------------------------------------------------------- API

    def ocr_pdf(
        self,
        source_path: str,
        *,
        languages: tuple[str, ...] = ("eng", "deu"),
    ) -> OcrResult:
        source = Path(source_path)
        self._validate_config(source)

        page_count = pdf_page_count(source)
        chunks = self._build_chunks(source, page_count)

        all_pages: list[OcrPageResult] = []
        try:
            for chunk_start, chunk_end, chunk_path in chunks:
                pages = self._call_chunk(
                    chunk_path,
                    languages=languages,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                )
                all_pages.extend(pages)
        finally:
            for _start, _end, path in chunks:
                if path != source and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        logger.warning("failed to clean chunk %s", path)

        return OcrResult(pages=tuple(all_pages), artifact_path=None)

    # -------------------------------------------------------------- helpers

    def _validate_config(self, source: Path) -> None:
        if not self._api.endpoint:
            raise OcrConfigError("external_api.endpoint is empty")
        parsed = urlparse(self._api.endpoint)
        if self._api.require_https and parsed.scheme != "https":
            raise OcrConfigError(
                f"external_api.endpoint must be https (got scheme {parsed.scheme!r})"
            )
        if not self._network.allow_external_egress:
            raise OcrEgressDeniedError(
                "external OCR call attempted but network.allow_external_egress is False"
            )
        host = parsed.hostname or ""
        if self._network.allowed_hosts and host not in self._network.allowed_hosts:
            raise OcrEgressDeniedError(f"host {host!r} is not in network.allowed_hosts")
        if not source.exists():
            raise OcrConfigError(f"source PDF does not exist: {source}")
        size_bytes = source.stat().st_size
        max_bytes = int(self._api.max_payload_mb * 1024 * 1024)
        if size_bytes > max_bytes:
            # We may still be able to handle this by chunking; but if a single
            # page exceeds the limit, the chunker can't help. Defer the hard
            # check to per-chunk uploads below; here we only warn.
            logger.warning(
                "source %s (%d bytes) exceeds max_payload_mb=%s; will attempt page-chunked uploads",
                source,
                size_bytes,
                self._api.max_payload_mb,
            )

    def _build_chunks(
        self,
        source: Path,
        page_count: int,
    ) -> list[tuple[int, int, Path]]:
        size_bytes = source.stat().st_size
        max_bytes = int(self._api.max_payload_mb * 1024 * 1024)
        if size_bytes <= max_bytes and page_count <= self._api.page_chunk_size:
            return [(1, page_count, source)]

        self._work_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[tuple[int, int, Path]] = []
        chunk_size = max(1, self._api.page_chunk_size)
        for chunk_idx, start in enumerate(range(1, page_count + 1, chunk_size), start=1):
            end = min(page_count, start + chunk_size - 1)
            target = self._work_dir / f"{source.stem}.chunk{chunk_idx:03d}.pdf"
            split_pdf_pages(source, target, start_page=start, end_page=end)
            chunk_bytes = target.stat().st_size
            if chunk_bytes > max_bytes:
                # Even a single chunk exceeds the limit. We refuse instead of
                # silently truncating.
                target.unlink(missing_ok=True)
                raise OcrPayloadTooLargeError(
                    f"chunk pages {start}..{end} ({chunk_bytes} bytes) "
                    f"exceeds max_payload_mb={self._api.max_payload_mb}"
                )
            chunks.append((start, end, target))
        return chunks

    def _call_chunk(
        self,
        chunk_path: Path,
        *,
        languages: tuple[str, ...],
        chunk_start: int,
        chunk_end: int,
    ) -> list[OcrPageResult]:
        attempts = _retry_schedule(
            max_retries=self._api.max_retries,
            base=self._api.backoff_base_seconds,
            cap=self._api.backoff_max_seconds,
        )

        last_error: OcrAdapterError | None = None
        for attempt in attempts:
            if attempt.sleep_before_seconds > 0:
                self._sleep(attempt.sleep_before_seconds)
            started = time.monotonic()
            try:
                pages = self._do_call(chunk_path, languages=languages)
                duration_ms = int((time.monotonic() - started) * 1000)
                self._audit(
                    "external_ocr_call",
                    {
                        "endpoint_host": urlparse(self._api.endpoint).hostname,
                        "attempt": attempt.number,
                        "status": "ok",
                        "page_range": [chunk_start, chunk_end],
                        "request_bytes": chunk_path.stat().st_size,
                        "duration_ms": duration_ms,
                    },
                )
                # Reindex page numbers into the global PDF page space.
                return [
                    OcrPageResult(
                        page_no=chunk_start + i,
                        text=p.text,
                        layout=p.layout,
                    )
                    for i, p in enumerate(pages)
                ]
            except OcrAdapterError as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                self._audit(
                    "external_ocr_call",
                    {
                        "endpoint_host": urlparse(self._api.endpoint).hostname,
                        "attempt": attempt.number,
                        "status": "error",
                        "error_code": exc.code,
                        "page_range": [chunk_start, chunk_end],
                        "duration_ms": duration_ms,
                    },
                )
                last_error = exc
                if not _is_retriable(exc):
                    raise

        assert last_error is not None
        raise last_error

    def _do_call(
        self,
        chunk_path: Path,
        *,
        languages: tuple[str, ...],
    ) -> list[OcrPageResult]:
        headers: dict[str, str] = {}
        if self._api.api_key:
            headers["Authorization"] = f"Bearer {self._api.api_key}"
        try:
            with chunk_path.open("rb") as fh:
                response = self._client.post(
                    self._api.endpoint,
                    headers=headers,
                    files={"file": (chunk_path.name, fh, "application/pdf")},
                    data={"languages": ",".join(languages)},
                    timeout=self._api.timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise OcrTimeoutError(f"external OCR timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise OcrTransportError(f"external OCR transport error: {exc}") from exc

        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> list[OcrPageResult]:
        status = response.status_code
        if status >= 500:
            raise OcrServerError(f"external OCR server error: HTTP {status}")
        if status >= 400:
            raise OcrAdapterError(
                f"external OCR client error: HTTP {status}",
                code="ocr_client_error",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OcrAdapterError(f"external OCR returned non-JSON body: {exc}") from exc

        if not isinstance(payload, dict):
            raise OcrAdapterError("external OCR response root must be an object")
        pages_raw = payload.get("pages")
        if not isinstance(pages_raw, list):
            raise OcrAdapterError("external OCR response missing 'pages' list")

        result: list[OcrPageResult] = []
        for entry in pages_raw:
            if not isinstance(entry, dict):
                raise OcrAdapterError("each page entry must be an object")
            page_no_raw = entry.get("page_no")
            text_raw = entry.get("text", "")
            layout_raw = entry.get("layout", {})
            if not isinstance(page_no_raw, int):
                raise OcrAdapterError("page entry missing integer 'page_no'")
            if not isinstance(text_raw, str):
                raise OcrAdapterError("page entry 'text' must be a string")
            if not isinstance(layout_raw, dict):
                raise OcrAdapterError("page entry 'layout' must be an object")
            result.append(
                OcrPageResult(
                    page_no=page_no_raw,
                    text=text_raw,
                    layout=layout_raw,
                )
            )
        return result


def _is_retriable(exc: OcrAdapterError) -> bool:
    return isinstance(exc, OcrTimeoutError | OcrTransportError | OcrServerError)
