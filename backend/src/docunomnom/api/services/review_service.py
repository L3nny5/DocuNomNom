"""API service that orchestrates Phase 4 review actions.

The service stitches together the pure derivation in
``core.usecases.review`` with the SQL repositories, the deterministic
PDF splitter, and the atomic exporter. Job state transitions are
delegated to ``SqlJobRepository.transition`` so the state machine
remains the single source of truth.

Design notes:

- Each finalize call performs (a) atomic export of every derived
  sub-part, (b) creation of one ``DocumentPart`` per derived sub-part
  with decision ``USER_CONFIRMED`` and an attached ``Export``, (c)
  marking the original part as ``USER_CONFIRMED`` (without an export of
  its own), and (d) closing the review item.
- The original part keeps its analysis attachment so audit data stays
  intact. The new sub-parts share the same analysis_id.
- Job state transitions: when this finalize closes the *last* open
  review item for the analysis, the job goes ``review_required ->
  completed`` (the ``user_finalize_all`` transition). Otherwise the job
  stays in ``review_required``.
- Reopen creates a new ``ReviewItem`` for the part and transitions the
  job ``completed -> review_required`` (the ``history_reopen`` transition).
- This service is API-side glue; the worker still owns the original
  pipeline. Phase 5+ may move some of this back into a use-case if the
  AI flow shares logic.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ...adapters.pdf import PdfReadError, split_pdf_pages
from ...config import Settings
from ...core.events import JobEventType
from ...core.models import (
    DocumentPart,
    DocumentPartDecision,
    Export,
    File,
    JobEvent,
    JobStatus,
    ReviewItem,
    ReviewItemStatus,
    ReviewMarker,
)
from ...core.ports.clock import ClockPort
from ...core.usecases.review import (
    DerivedSubpart,
    InvalidMarkersError,
    derive_subparts_from_markers,
)
from ...storage.db import (
    SqlAnalysisRepository,
    SqlDocumentPartRepository,
    SqlExportRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobRepository,
    SqlReviewItemRepository,
    SqlReviewMarkerRepository,
)
from ...storage.files import atomic_publish

logger = logging.getLogger(__name__)


class ReviewServiceError(RuntimeError):
    """Domain-friendly error type for the API layer to convert to HTTP 4xx/5xx."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    """Return value of :meth:`ReviewService.finalize`."""

    item_id: int
    job_id: int
    job_status: JobStatus
    exported_part_ids: list[int]
    derived_count: int


@dataclass(frozen=True, slots=True)
class ReopenResult:
    """Return value of :meth:`ReviewService.reopen_history`."""

    review_item_id: int
    part_id: int
    job_id: int


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ReviewService:
    """Stateless orchestrator; constructed per request with a session."""

    def __init__(self, session: Session, settings: Settings, clock: ClockPort) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock
        self._items = SqlReviewItemRepository(session)
        self._markers = SqlReviewMarkerRepository(session)
        self._parts = SqlDocumentPartRepository(session)
        self._analyses = SqlAnalysisRepository(session)
        self._files = SqlFileRepository(session)
        self._jobs = SqlJobRepository(session)
        self._exports = SqlExportRepository(session)
        self._events = SqlJobEventRepository(session)

    # -------------------------------------------------------------- markers

    def replace_markers(self, item_id: int, markers: list[ReviewMarker]) -> list[ReviewMarker]:
        """Replace the marker set for ``item_id`` atomically.

        Validates each marker against the part's page range. Sets the
        item to ``IN_PROGRESS`` so the listing shows reviewer progress.
        """
        item = self._items.get(item_id)
        if item is None:
            raise ReviewServiceError("not_found", f"ReviewItem {item_id} not found")
        part = self._parts.get(item.part_id)
        if part is None:
            raise ReviewServiceError("not_found", "Linked DocumentPart not found")

        for marker in markers:
            if marker.page_no < part.start_page or marker.page_no > part.end_page:
                raise ReviewServiceError(
                    "invalid_marker",
                    (
                        f"marker page {marker.page_no} outside part range "
                        f"{part.start_page}..{part.end_page}"
                    ),
                )

        result = self._markers.replace_for_item(item_id, markers)
        if item.status is ReviewItemStatus.OPEN:
            self._items.transition(item_id, new_status=ReviewItemStatus.IN_PROGRESS)
        return result

    # -------------------------------------------------------------- finalize

    def finalize(self, item_id: int) -> FinalizeResult:
        """Apply persisted markers, export sub-parts, and close the item.

        Raises :class:`ReviewServiceError` for any condition that makes the
        finalize unsafe (missing PDF, illegal marker set, etc.). On the
        happy path the returned :class:`FinalizeResult` carries the final
        job status and the IDs of every newly-created exported part.
        """
        item = self._items.get(item_id)
        if item is None:
            raise ReviewServiceError("not_found", f"ReviewItem {item_id} not found")
        if item.status is ReviewItemStatus.DONE:
            raise ReviewServiceError("already_done", "ReviewItem is already finalized")

        part = self._parts.get(item.part_id)
        if part is None or part.id is None:
            raise ReviewServiceError("not_found", "Linked DocumentPart not found")

        from ...storage.db.models import AnalysisORM

        analysis = self._session.get(AnalysisORM, part.analysis_id)
        if analysis is None:
            raise ReviewServiceError("not_found", "Linked Analysis not found")

        job = self._jobs.get(analysis.job_id)
        if job is None or job.id is None:
            raise ReviewServiceError("not_found", "Linked Job not found")
        file = self._files.get(job.file_id)
        if file is None:
            raise ReviewServiceError("not_found", "Linked File not found")

        markers = self._markers.list_for_item(item_id)
        try:
            derived = derive_subparts_from_markers(part, markers)
        except InvalidMarkersError as exc:
            raise ReviewServiceError("invalid_markers", str(exc)) from exc

        pdf_path = self._resolve_pdf_path(analysis_artifact=analysis.ocr_artifact_path, file=file)
        if not pdf_path.exists():
            raise ReviewServiceError("pdf_missing", f"Source PDF not found at {pdf_path}")

        exported_ids = self._export_subparts(
            job_id=job.id,
            analysis_id=part.analysis_id,
            file_original_name=file.original_name,
            pdf_path=pdf_path,
            derived=derived,
        )

        # Mark the original part user-confirmed so history shows the
        # reviewed lineage; the new sub-parts are the actual exports.
        self._parts.update_decision(part.id, decision=DocumentPartDecision.USER_CONFIRMED.value)

        finished_at = self._clock.now()
        self._items.transition(
            item_id,
            new_status=ReviewItemStatus.DONE,
            finished_at=finished_at,
        )

        self._events.append(
            JobEvent(
                job_id=job.id,
                type="review_finalized",
                payload={
                    "review_item_id": item_id,
                    "part_id": part.id,
                    "exported_part_ids": exported_ids,
                    "derived_count": len(derived),
                },
            )
        )

        # Job-level state transition: only if this was the last open item.
        remaining_open = self._items.count_open_for_analysis(part.analysis_id)
        new_job_status = job.status
        if remaining_open == 0 and job.status is JobStatus.REVIEW_REQUIRED:
            updated = self._jobs.transition(job.id, new_status=JobStatus.COMPLETED)
            new_job_status = updated.status
            self._events.append(
                JobEvent(
                    job_id=job.id,
                    type=JobEventType.COMPLETED.value,
                    payload={"trigger": "user_finalize_all"},
                )
            )

        return FinalizeResult(
            item_id=item_id,
            job_id=job.id,
            job_status=new_job_status,
            exported_part_ids=exported_ids,
            derived_count=len(derived),
        )

    def _export_subparts(
        self,
        *,
        job_id: int,
        analysis_id: int,
        file_original_name: str,
        pdf_path: Path,
        derived: list[DerivedSubpart],
    ) -> list[int]:
        output_dir = Path(self._settings.paths.output_dir)
        work_root = Path(self._settings.paths.work_dir) / "review-exports" / f"job-{job_id}-item"
        work_root.mkdir(parents=True, exist_ok=True)
        require_same_fs = self._settings.exporter.require_same_filesystem
        template = self._settings.exporter.output_basename_template
        stem = Path(file_original_name).stem

        exported_ids: list[int] = []
        for d in derived:
            sub_part = DocumentPart(
                analysis_id=analysis_id,
                start_page=d.start_page,
                end_page=d.end_page,
                decision=DocumentPartDecision.USER_CONFIRMED,
                confidence=1.0,
            )
            persisted = list(self._parts.add_many([sub_part]))[0]
            if persisted.id is None:
                raise ReviewServiceError("part_persist_failed", "Could not persist sub-part")

            try:
                desired_name = template.format(stem=f"{stem}_review", index=d.index)
                work_pdf = work_root / f"part-{d.index:03d}.pdf"
                split_pdf_pages(
                    pdf_path,
                    work_pdf,
                    start_page=d.start_page,
                    end_page=d.end_page,
                )
            except PdfReadError as exc:
                raise ReviewServiceError("pdf_split_failed", str(exc)) from exc

            try:
                published = atomic_publish(
                    source_path=work_pdf,
                    target_dir=output_dir,
                    desired_name=desired_name,
                    require_same_device=require_same_fs,
                )
            except Exception as exc:
                logger.exception("atomic publish failed for derived sub-part %s", d.index)
                raise ReviewServiceError("export_failed", str(exc)) from exc

            sha = _sha256_path(published)
            export = self._exports.add(
                Export(
                    part_id=persisted.id,
                    output_path=str(published),
                    output_name=published.name,
                    sha256=sha,
                )
            )
            if export.id is None:
                raise ReviewServiceError("export_persist_failed", "Could not persist export")
            self._parts.attach_export(persisted.id, export.id)
            self._events.append(
                JobEvent(
                    job_id=job_id,
                    type=JobEventType.EXPORT_COMPLETED.value,
                    payload={
                        "part_id": persisted.id,
                        "output_name": published.name,
                        "sha256": sha,
                        "source": "review",
                    },
                )
            )
            exported_ids.append(persisted.id)

        return exported_ids

    # ---------------------------------------------------------------- pdf

    def resolve_pdf(self, item_id: int) -> Path:
        """Return the PDF path that should be served for ``item_id``.

        Prefers the analysis OCR artifact (it is what the splitter
        operates on) and falls back to the original source PDF. Raises
        :class:`ReviewServiceError` for missing items / missing files.
        """
        item = self._items.get(item_id)
        if item is None:
            raise ReviewServiceError("not_found", f"ReviewItem {item_id} not found")
        part = self._parts.get(item.part_id)
        if part is None:
            raise ReviewServiceError("not_found", "Linked DocumentPart not found")
        from ...storage.db.models import AnalysisORM

        analysis = self._session.get(AnalysisORM, part.analysis_id)
        if analysis is None:
            raise ReviewServiceError("not_found", "Linked Analysis not found")
        job = self._jobs.get(analysis.job_id)
        if job is None:
            raise ReviewServiceError("not_found", "Linked Job not found")
        file = self._files.get(job.file_id)
        if file is None:
            raise ReviewServiceError("not_found", "Linked File not found")

        return self._resolve_pdf_path(
            analysis_artifact=analysis.ocr_artifact_path,
            file=file,
        )

    def _resolve_pdf_path(self, *, analysis_artifact: str | None, file: File) -> Path:
        if analysis_artifact:
            candidate = Path(analysis_artifact)
            if candidate.exists():
                return candidate
        return Path(file.source_path)

    # ---------------------------------------------------------------- reopen

    def reopen_history(self, part_id: int) -> ReopenResult:
        """Reopen an exported part for review.

        Creates a new ``ReviewItem`` for the part. If the owning job is
        currently ``COMPLETED`` it transitions to ``REVIEW_REQUIRED`` via
        the ``history_reopen`` allowed transition. Existing audit/history
        is preserved (the original ``Export`` row is not touched).
        """
        part = self._parts.get(part_id)
        if part is None:
            raise ReviewServiceError("not_found", f"DocumentPart {part_id} not found")
        existing = self._items.get_by_part(part_id)
        if existing is not None and existing.status is not ReviewItemStatus.DONE:
            raise ReviewServiceError(
                "already_open",
                "An open review item already exists for this part",
            )
        from ...storage.db.models import AnalysisORM

        analysis = self._session.get(AnalysisORM, part.analysis_id)
        if analysis is None:
            raise ReviewServiceError("not_found", "Linked Analysis not found")
        job = self._jobs.get(analysis.job_id)
        if job is None or job.id is None:
            raise ReviewServiceError("not_found", "Linked Job not found")

        # Reset the existing review item if it was previously done; otherwise
        # add a fresh one. v1 keeps it at one item per part to match the
        # uniqueness constraint on ``review_items.part_id``.
        if existing is not None and existing.status is ReviewItemStatus.DONE:
            assert existing.id is not None
            self._items.transition(
                existing.id,
                new_status=ReviewItemStatus.OPEN,
                finished_at=None,
            )
            self._markers.replace_for_item(existing.id, [])
            review_item_id = existing.id
        else:
            created = self._items.add(
                ReviewItem(
                    part_id=part_id,
                    status=ReviewItemStatus.OPEN,
                )
            )
            assert created.id is not None
            review_item_id = created.id

        if job.status is JobStatus.COMPLETED:
            self._jobs.transition(job.id, new_status=JobStatus.REVIEW_REQUIRED)
            self._events.append(
                JobEvent(
                    job_id=job.id,
                    type="history_reopened",
                    payload={"part_id": part_id, "review_item_id": review_item_id},
                )
            )

        return ReopenResult(
            review_item_id=review_item_id,
            part_id=part_id,
            job_id=job.id,
        )
