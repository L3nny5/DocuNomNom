"""Smoke tests that ensure the package skeleton is importable."""

import docunomnom


def test_package_version_is_string() -> None:
    assert isinstance(docunomnom.__version__, str)


def test_subpackages_import() -> None:
    # All declared layers must import cleanly even when they only contain
    # placeholder modules. This protects the hexagonal boundaries.
    import importlib

    for module in [
        "docunomnom.api",
        "docunomnom.api.routers",
        "docunomnom.core",
        "docunomnom.core.models",
        "docunomnom.core.usecases",
        "docunomnom.core.ports",
        "docunomnom.core.rules",
        "docunomnom.core.confidence",
        "docunomnom.core.evidence",
        "docunomnom.adapters",
        "docunomnom.adapters.ocr",
        "docunomnom.adapters.ai_split",
        "docunomnom.adapters.pdf",
        "docunomnom.adapters.http",
        "docunomnom.storage",
        "docunomnom.storage.db",
        "docunomnom.storage.files",
        "docunomnom.worker",
        "docunomnom.config",
        "docunomnom.i18n",
    ]:
        importlib.import_module(module)
