"""Tests for the worker's OCR-port factory selector."""

from __future__ import annotations

from pathlib import Path

import pytest

from docunomnom.adapters.ocr import GenericExternalOcrAdapter, OcrmypdfAdapter
from docunomnom.config import (
    AiSettings,
    ExporterSettings,
    ExternalOcrApiSettings,
    IngestionSettings,
    NetworkSettings,
    OcrmypdfSettings,
    OcrSettings,
    PathSettings,
    Settings,
    SplitterSettings,
    StorageSettings,
    WorkerSettings,
)
from docunomnom.core.models import OcrBackend
from docunomnom.worker.ocr_factory import build_ocr_port_factory


def _settings(backend: OcrBackend) -> Settings:
    return Settings(
        paths=PathSettings(),
        storage=StorageSettings(),
        ingestion=IngestionSettings(),
        worker=WorkerSettings(),
        ocr=OcrSettings(
            backend=backend,
            languages=("eng",),
            ocrmypdf=OcrmypdfSettings(),
            external_api=ExternalOcrApiSettings(endpoint="https://x.example.com"),
        ),
        network=NetworkSettings(allow_external_egress=True),
        splitter=SplitterSettings(),
        exporter=ExporterSettings(),
        ai=AiSettings(),
    )


def test_factory_returns_ocrmypdf_when_selected(tmp_path: Path) -> None:
    factory = build_ocr_port_factory(_settings(OcrBackend.OCRMYPDF))
    port = factory(tmp_path, lambda _t, _p: None)
    assert isinstance(port, OcrmypdfAdapter)


def test_factory_returns_external_api_when_selected(tmp_path: Path) -> None:
    factory = build_ocr_port_factory(_settings(OcrBackend.EXTERNAL_API))
    port = factory(tmp_path, lambda _t, _p: None)
    assert isinstance(port, GenericExternalOcrAdapter)


def test_factory_rejects_unknown_backend(tmp_path: Path) -> None:
    """Forcing an unsupported backend value (bypassing enum validation) must
    raise from the factory dispatch."""
    s = _settings(OcrBackend.OCRMYPDF)
    # Mutate the (validated) settings tree to inject an unknown backend
    # value so we can exercise the factory's dispatch fallback.
    object.__setattr__(s.ocr, "backend", "bogus_backend")
    factory = build_ocr_port_factory(s)
    with pytest.raises(ValueError, match="unsupported OCR backend"):
        factory(tmp_path, lambda _t, _p: None)
