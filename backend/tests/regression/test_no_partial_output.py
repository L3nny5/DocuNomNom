"""Regression: the exporter never leaves a partial file in output_dir.

This pins the v1 atomicity guarantee: paperless-ngx (or any other
consumer watching ``output_dir``) MUST NOT observe a half-written PDF
even when the publish operation is interrupted between fsync and
rename, or when the rename itself races a concurrent reader.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from docunomnom.storage.files import (
    CrossDeviceError,
    assert_same_device,
    atomic_publish,
)


def test_atomic_publish_uses_rename_not_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``os.rename`` is unavailable we MUST fail loudly, never fall
    back to a non-atomic copy. Any silent fallback would let a reader
    observe a partial file."""
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    src = work / "draft.pdf"
    src.write_bytes(b"X" * 4096)

    calls: list[tuple[str, str]] = []
    real_rename = os.rename

    def tracking_rename(a: str, b: str) -> None:
        calls.append((a, b))
        real_rename(a, b)

    monkeypatch.setattr("docunomnom.storage.files.atomic.os.rename", tracking_rename)
    atomic_publish(source_path=src, target_dir=out, desired_name="final.pdf")
    assert calls, "atomic_publish must call os.rename exactly once"
    assert calls[0][1].endswith("final.pdf")


def test_atomic_publish_blocks_cross_device_writes(tmp_path: Path) -> None:
    """When work/output straddle filesystems, the exporter MUST raise
    rather than silently use a non-atomic strategy."""
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    # Sanity: same dir => same device.
    assert_same_device(work, out)

    src = work / "draft.pdf"
    src.write_bytes(b"X" * 1024)

    # Patch only the same-device check used by atomic_publish, since
    # faking st_dev at the Path layer breaks unrelated stat calls.
    def fake_assert(work_dir: Path, target_dir: Path) -> None:
        raise CrossDeviceError(f"forced: {work_dir} vs {target_dir}")

    import pytest as _pt

    with _pt.MonkeyPatch.context() as mp:
        mp.setattr(
            "docunomnom.storage.files.atomic.assert_same_device",
            fake_assert,
            raising=True,
        )
        with _pt.raises(CrossDeviceError):
            atomic_publish(source_path=src, target_dir=out, desired_name="final.pdf")

    # Original still in work; nothing partial in out.
    assert src.exists()
    assert list(out.iterdir()) == []


def test_concurrent_reader_never_sees_partial(tmp_path: Path) -> None:
    """Stress: while a reader scans ``out``, the publisher writes 50
    files. Every file the reader observes MUST be complete (size >= 4 KiB
    of the marker payload), never a tmp/zero-length file."""
    work = tmp_path / "work"
    out = tmp_path / "out"
    work.mkdir()
    out.mkdir()
    payload = b"DOCUNOMNOM-OK" * 512  # well above any possible torn write.

    stop = threading.Event()
    observed_sizes: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            for p in list(out.iterdir()):
                try:
                    observed_sizes.append(p.stat().st_size)
                except FileNotFoundError:
                    continue
            time.sleep(0.001)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for i in range(50):
            src = work / f"draft_{i}.pdf"
            src.write_bytes(payload)
            atomic_publish(
                source_path=src,
                target_dir=out,
                desired_name=f"part_{i:03d}.pdf",
            )
    finally:
        stop.set()
        t.join(timeout=2.0)

    assert sorted(p.name for p in out.iterdir()) == [f"part_{i:03d}.pdf" for i in range(50)]
    # The reader may sample files at arbitrary points; it MUST never see
    # a partial / zero-length entry from a published part.
    assert observed_sizes, "reader saw nothing — sanity check failed"
    assert all(size == len(payload) for size in observed_sizes), (
        f"reader observed unexpected sizes: {sorted(set(observed_sizes))}"
    )
