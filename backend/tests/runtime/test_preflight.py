"""Phase 6 preflight tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docunomnom.config import Settings
from docunomnom.config.settings import (
    AiSettings,
    AiThresholdSettings,
    ExporterSettings,
    NetworkSettings,
    PathSettings,
    SplitterSettings,
    StorageSettings,
)
from docunomnom.core.models import AiBackend, AiMode
from docunomnom.runtime.preflight import (
    PreflightError,
    SingleWorkerLockError,
    _check_sqlite_safe_mount,
    _classify_mount,
    _sqlite_file_path,
    acquire_single_worker_lock,
    run_preflight,
)


def _settings_for(tmp_path: Path) -> Settings:
    """A Settings object whose mounts all live under ``tmp_path``."""
    paths = PathSettings(
        input_dir=str(tmp_path / "input"),
        output_dir=str(tmp_path / "output"),
        work_dir=str(tmp_path / "work"),
        archive_dir=str(tmp_path / "archive"),
    )
    for sub in ("input", "output", "work", "archive"):
        (tmp_path / sub).mkdir()

    return Settings(
        log_level="INFO",
        paths=paths,
        storage=StorageSettings(
            database_url=f"sqlite:///{tmp_path / 'docunomnom.sqlite3'}",
            ocr_artifact_dir=str(tmp_path / "work" / "ocr"),
        ),
        exporter=ExporterSettings(require_same_filesystem=True, archive_after_export=True),
        ai=AiSettings(),
        network=NetworkSettings(),
        splitter=SplitterSettings(),
    )


def test_run_preflight_happy_path(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    report = run_preflight(settings, raise_on_failure=False)
    assert report.ok, [c for c in report.checks if not c.ok]


def test_missing_input_dir_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    (tmp_path / "input").rmdir()
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert "input_dir" in exc.value.message


def test_unwritable_output_dir_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    out = tmp_path / "output"
    os.chmod(out, 0o500)
    try:
        with pytest.raises(PreflightError) as exc:
            run_preflight(settings)
        assert "output_dir" in exc.value.message
    finally:
        os.chmod(out, 0o755)


def test_ai_mode_without_backend_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.ai.mode = AiMode.VALIDATE
    settings.ai.backend = AiBackend.NONE
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert exc.value.code == "ai.mode_requires_backend"


def test_openai_without_egress_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.ai.backend = AiBackend.OPENAI
    settings.ai.mode = AiMode.VALIDATE
    settings.network.allow_external_egress = False
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert "egress" in exc.value.message


def test_openai_without_allowed_hosts_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.ai.backend = AiBackend.OPENAI
    settings.ai.mode = AiMode.VALIDATE
    settings.network.allow_external_egress = True
    settings.network.allowed_hosts = ()
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert "allowed_hosts" in exc.value.message


def test_openai_missing_api_key_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings_for(tmp_path)
    settings.ai.backend = AiBackend.OPENAI
    settings.ai.mode = AiMode.VALIDATE
    settings.network.allow_external_egress = True
    settings.network.allowed_hosts = ("api.openai.com",)
    settings.ai.openai.api_key_env = "DOCUNOMNOM_TEST_MISSING_KEY"
    monkeypatch.delenv("DOCUNOMNOM_TEST_MISSING_KEY", raising=False)
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert exc.value.code == "ai.openai_api_key_present"


def test_threshold_band_inverted_fails(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.ai.thresholds = AiThresholdSettings(
        auto_export_min_confidence=0.5,
        review_required_below=0.8,
    )
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert exc.value.code == "ai.thresholds_band"


def test_splitter_weights_sum_must_be_one(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.splitter = SplitterSettings(
        keyword_weight=0.5,
        layout_weight=0.5,
        page_number_weight=0.5,
    )
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert exc.value.code == "splitter.weights_sum"


def test_pipeline_version_must_be_semver(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    settings.runtime.pipeline_version = "broken"
    with pytest.raises(PreflightError) as exc:
        run_preflight(settings)
    assert exc.value.code == "runtime.pipeline_version"


# --- SQLite mount classification ------------------------------------------


def test_sqlite_file_path_handles_in_memory() -> None:
    assert _sqlite_file_path("sqlite://") is None
    assert _sqlite_file_path("sqlite:///:memory:") is None
    p = _sqlite_file_path("sqlite:////tmp/foo.db")
    assert p == Path("/tmp/foo.db").resolve()


def test_classify_mount_picks_longest_match() -> None:
    mounts = (
        ("/", "ext4"),
        ("/data", "zfs"),
        ("/data/share", "nfs"),
    )
    assert _classify_mount(Path("/data/share/db.sqlite3"), mounts) == ("/data/share", "nfs")
    assert _classify_mount(Path("/data/local/db.sqlite3"), mounts) == ("/data", "zfs")
    assert _classify_mount(Path("/var/log"), mounts) == ("/", "ext4")


def test_check_sqlite_safe_mount_rejects_nfs(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    mounts = (
        ("/", "ext4"),
        (str(tmp_path), "nfs"),
    )
    result = _check_sqlite_safe_mount(
        f"sqlite:///{db}",
        mounts_provider=lambda: mounts,
    )
    assert not result.ok
    assert "nfs" in result.detail.lower()


def test_check_sqlite_safe_mount_accepts_zfs(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    mounts = (
        ("/", "ext4"),
        (str(tmp_path), "zfs"),
    )
    result = _check_sqlite_safe_mount(
        f"sqlite:///{db}",
        mounts_provider=lambda: mounts,
    )
    assert result.ok


def test_check_sqlite_safe_mount_skips_when_no_proc_mounts(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    result = _check_sqlite_safe_mount(
        f"sqlite:///{db}",
        mounts_provider=lambda: (),
    )
    assert result.ok


# --- Single-worker advisory lock ------------------------------------------


def test_acquire_single_worker_lock_writes_pid_file(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    lock = acquire_single_worker_lock(work)
    assert lock.path.exists()
    assert int(lock.path.read_text().strip()) == os.getpid()
    lock.release()
    assert not lock.path.exists()


def test_acquire_single_worker_lock_reclaims_stale(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    stale = work / ".docunomnom_worker.lock"
    stale.write_text("999999\n", encoding="utf-8")
    lock = acquire_single_worker_lock(work)
    assert int(lock.path.read_text().strip()) == os.getpid()
    lock.release()


def test_acquire_single_worker_lock_refuses_live_owner(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    live = work / ".docunomnom_worker.lock"
    live.write_text(f"{os.getppid()}\n", encoding="utf-8")
    with pytest.raises(SingleWorkerLockError):
        acquire_single_worker_lock(work)


def test_single_worker_lock_context_manager(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    with acquire_single_worker_lock(work) as lock:
        assert lock.path.exists()
    assert not lock.path.exists()
