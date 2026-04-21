"""Default ``OcrPort`` factory for the worker.

Wraps the OCRmyPDF and Generic External API adapters and dispatches based on
``settings.ocr.backend``. Kept separate from ``processor.py`` so tests can
inject a fake factory without going through the real adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..adapters.ocr import GenericExternalOcrAdapter, OcrmypdfAdapter
from ..config import Settings
from ..core.models import OcrBackend
from ..core.ports.ocr import OcrPort

AuditCb = Callable[[str, dict[str, Any]], None]


def build_ocr_port_factory(
    settings: Settings,
) -> Callable[[Path, AuditCb], OcrPort]:
    """Return a factory ``(work_dir, audit_cb) -> OcrPort``.

    The chosen backend is fixed for the lifetime of the worker process and
    is captured here from the supplied ``settings``.
    """

    def factory(work_dir: Path, audit_cb: AuditCb) -> OcrPort:
        backend = settings.ocr.backend
        if backend is OcrBackend.OCRMYPDF:
            return OcrmypdfAdapter(
                settings=settings.ocr.ocrmypdf,
                work_dir=work_dir,
            )
        if backend is OcrBackend.EXTERNAL_API:
            return GenericExternalOcrAdapter(
                api=settings.ocr.external_api,
                network=settings.network,
                work_dir=work_dir,
                audit_callback=audit_cb,
            )
        raise ValueError(f"unsupported OCR backend: {backend!r}")

    return factory
