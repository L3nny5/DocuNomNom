"""Local OCR via the ``ocrmypdf`` Python API.

The adapter:

1. Runs ``ocrmypdf.ocr`` against the source PDF, writing the OCR'd output
   into a caller-supplied work directory.
2. Asks ocrmypdf for a sidecar text file that contains the OCR text
   separated by form-feeds (one chunk per page).
3. Reads the page count from the OCR'd output and parses the sidecar into
   ``OcrPageResult`` items.

The ``ocrmypdf`` package itself is imported lazily so unit tests on machines
without the binary can still import this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ...config import OcrmypdfSettings
from ...core.ports.ocr import OcrPageResult, OcrResult
from ..pdf import parse_sidecar_text, pdf_page_count
from .errors import OcrAdapterError, OcrConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _OcrmypdfRunOutputs:
    """Files produced by a single ocrmypdf run."""

    ocr_pdf_path: Path
    sidecar_path: Path


class OcrmypdfAdapter:
    """``OcrPort`` implementation backed by ``ocrmypdf``.

    The optional ``runner`` parameter exists purely for testability — tests
    inject a fake that mimics ``ocrmypdf.ocr`` and writes deterministic
    output files. Production code uses the default runner which calls into
    the real ocrmypdf API.
    """

    def __init__(
        self,
        *,
        settings: OcrmypdfSettings,
        work_dir: Path,
        runner: Callable[..., None] | None = None,
    ) -> None:
        self._settings = settings
        self._work_dir = work_dir
        self._runner = runner

    def ocr_pdf(
        self,
        source_path: str,
        *,
        languages: tuple[str, ...] = ("eng", "deu"),
    ) -> OcrResult:
        source = Path(source_path)
        if not source.exists():
            raise OcrConfigError(f"source PDF does not exist: {source}")

        self._work_dir.mkdir(parents=True, exist_ok=True)
        outputs = self._build_output_paths(source)

        runner = self._runner or self._default_runner
        try:
            runner(
                input_file=str(source),
                output_file=str(outputs.ocr_pdf_path),
                sidecar=str(outputs.sidecar_path),
                language="+".join(languages),
                deskew=self._settings.deskew,
                rotate_pages=self._settings.rotate_pages,
                skip_text=self._settings.skip_text,
                optimize=self._settings.optimize,
                jobs=self._settings.jobs,
                progress_bar=False,
            )
        except OcrAdapterError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("ocrmypdf run failed for %s", source)
            raise OcrAdapterError(f"ocrmypdf failed: {exc}") from exc

        if not outputs.ocr_pdf_path.exists():
            raise OcrAdapterError(f"ocrmypdf did not produce output PDF at {outputs.ocr_pdf_path}")

        page_count = pdf_page_count(outputs.ocr_pdf_path)
        sidecar_text = (
            outputs.sidecar_path.read_text(encoding="utf-8", errors="replace")
            if outputs.sidecar_path.exists()
            else ""
        )
        per_page = parse_sidecar_text(sidecar_text, page_count=page_count)

        pages = tuple(
            OcrPageResult(page_no=i + 1, text=text, layout={}) for i, text in enumerate(per_page)
        )
        return OcrResult(pages=pages, artifact_path=str(outputs.ocr_pdf_path))

    def _build_output_paths(self, source: Path) -> _OcrmypdfRunOutputs:
        stem = source.stem
        return _OcrmypdfRunOutputs(
            ocr_pdf_path=self._work_dir / f"{stem}.ocr.pdf",
            sidecar_path=self._work_dir / f"{stem}.ocr.txt",
        )

    @staticmethod
    def _default_runner(**kwargs: object) -> None:
        """Real production runner. Imported lazily so tests can run without
        the ocrmypdf binary."""
        try:
            import ocrmypdf
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise OcrConfigError(
                "ocrmypdf is not installed but the OCRmyPDF backend was selected"
            ) from exc
        ocrmypdf.ocr(**kwargs)
