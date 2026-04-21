"""OCR adapters."""

from .errors import (
    OcrAdapterError,
    OcrConfigError,
    OcrEgressDeniedError,
    OcrPayloadTooLargeError,
    OcrServerError,
    OcrTimeoutError,
    OcrTransportError,
)
from .generic_api import GenericExternalOcrAdapter
from .ocrmypdf import OcrmypdfAdapter

__all__ = [
    "GenericExternalOcrAdapter",
    "OcrAdapterError",
    "OcrConfigError",
    "OcrEgressDeniedError",
    "OcrPayloadTooLargeError",
    "OcrServerError",
    "OcrTimeoutError",
    "OcrTransportError",
    "OcrmypdfAdapter",
]
