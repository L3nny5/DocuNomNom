"""Tests for the file stability watcher."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from docunomnom.adapters.clock import FixedClock
from docunomnom.config import IngestionSettings, Settings
from docunomnom.storage.db import (
    SqlConfigSnapshotRepository,
    SqlFileRepository,
    SqlJobEventRepository,
    SqlJobRepository,
)
from docunomnom.worker.watcher import StabilityWatcher, settings_to_config_snapshot

PDF_HEADER = b"%PDF-1.4\n%binarygunk\n"


def _build_watcher(
    *,
    session: Session,
    clock: FixedClock,
    input_dir: Path,
    stability: float = 5.0,
    require_magic: bool = True,
) -> StabilityWatcher:
    ingestion = IngestionSettings(
        poll_interval_seconds=1.0,
        stability_window_seconds=stability,
        require_pdf_magic=require_magic,
    )
    settings = Settings(ingestion=ingestion)
    return StabilityWatcher(
        input_dir=input_dir,
        ingestion=settings.ingestion,
        pipeline_version=settings.runtime.pipeline_version,
        clock=clock,
        files=SqlFileRepository(session),
        jobs=SqlJobRepository(session),
        events=SqlJobEventRepository(session),
        snapshots=SqlConfigSnapshotRepository(session),
        snapshot_factory=lambda: settings_to_config_snapshot(settings),
    )


def test_ignores_non_pdf(tmp_path: Path, session: Session, fixed_clock: FixedClock) -> None:
    (tmp_path / "note.txt").write_bytes(b"hello")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path)
    result = w.scan_once()
    assert result.enqueued_jobs == []
    assert (tmp_path / "note.txt") in result.skipped_invalid


def test_ignores_dotfile_and_partial(
    tmp_path: Path, session: Session, fixed_clock: FixedClock
) -> None:
    (tmp_path / ".inprogress").write_bytes(PDF_HEADER)
    (tmp_path / "x.partial").write_bytes(PDF_HEADER)
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path)
    result = w.scan_once()
    assert result.enqueued_jobs == []
    assert any(p.name == ".inprogress" for p in result.skipped_ignored)
    assert any(p.name == "x.partial" for p in result.skipped_ignored)


def test_requires_pdf_magic(tmp_path: Path, session: Session, fixed_clock: FixedClock) -> None:
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"NOTAPDF")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path, stability=0.0)
    # First scan establishes the observation.
    w.scan_once()
    fixed_clock.advance(seconds=1)
    result = w.scan_once()
    assert result.enqueued_jobs == []
    assert pdf in result.skipped_invalid


def test_unstable_file_is_not_enqueued(
    tmp_path: Path, session: Session, fixed_clock: FixedClock
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(PDF_HEADER + b"first")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path, stability=10.0)

    r1 = w.scan_once()
    assert pdf in r1.skipped_unstable

    fixed_clock.advance(seconds=2)
    pdf.write_bytes(PDF_HEADER + b"second")  # changes size + mtime
    r2 = w.scan_once()
    assert pdf in r2.skipped_unstable
    assert r2.enqueued_jobs == []


def test_stable_file_is_enqueued(tmp_path: Path, session: Session, fixed_clock: FixedClock) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(PDF_HEADER + b"hello world")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path, stability=5.0)

    w.scan_once()  # first observation, not yet stable
    fixed_clock.advance(seconds=10)
    result = w.scan_once()
    assert len(result.enqueued_jobs) == 1


def test_duplicate_active_run_key_is_skipped(
    tmp_path: Path, session: Session, fixed_clock: FixedClock
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(PDF_HEADER + b"same content")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path, stability=1.0)

    w.scan_once()
    fixed_clock.advance(seconds=2)
    first = w.scan_once()
    assert len(first.enqueued_jobs) == 1

    # Identical file appears in a different name. Stable. Should not enqueue
    # because the active run_key already exists for the same content +
    # snapshot + pipeline version.
    pdf2 = tmp_path / "duplicate.pdf"
    pdf2.write_bytes(PDF_HEADER + b"same content")
    w.scan_once()
    fixed_clock.advance(seconds=2)
    second = w.scan_once()
    assert second.enqueued_jobs == []
    assert pdf2 in second.skipped_active_run_key


def test_disappeared_file_is_forgotten(
    tmp_path: Path, session: Session, fixed_clock: FixedClock
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(PDF_HEADER + b"hi")
    w = _build_watcher(session=session, clock=fixed_clock, input_dir=tmp_path, stability=5.0)
    w.scan_once()
    pdf.unlink()
    fixed_clock.advance(seconds=10)
    result = w.scan_once()
    assert result.enqueued_jobs == []


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> Iterator[None]:
    from docunomnom.config import reset_settings_cache

    reset_settings_cache()
    yield
    reset_settings_cache()
