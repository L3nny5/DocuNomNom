"""OCR adapter error hierarchy.

These map to the recoverable / fatal split in the worker loop. Any
``OcrAdapterError`` raised by an adapter must be a normalized error; it is
either bubbled up to the processor or turned into a ``JobProcessingError``
with a stable code.
"""

from __future__ import annotations


class OcrAdapterError(RuntimeError):
    """Base class for OCR adapter failures with a stable error code."""

    code: str = "ocr_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class OcrConfigError(OcrAdapterError):
    """The OCR adapter is misconfigured (missing endpoint, etc.)."""

    code = "ocr_config_error"


class OcrEgressDeniedError(OcrAdapterError):
    """An external OCR call was attempted while egress is disallowed."""

    code = "ocr_egress_denied"


class OcrPayloadTooLargeError(OcrAdapterError):
    """The PDF exceeds the configured external API payload limit."""

    code = "ocr_payload_too_large"


class OcrTimeoutError(OcrAdapterError):
    """The OCR call exceeded the configured timeout."""

    code = "ocr_timeout"


class OcrTransportError(OcrAdapterError):
    """A transport-layer (network/HTTP) error occurred."""

    code = "ocr_transport_error"


class OcrServerError(OcrAdapterError):
    """The OCR server returned a non-recoverable HTTP error."""

    code = "ocr_server_error"
