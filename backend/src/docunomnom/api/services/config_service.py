"""Persistence-backed config service for the API.

Holds the single ``ConfigProfile`` (named ``DEFAULT_PROFILE_NAME``) that
v1 uses to back the ``/config`` and ``/config/keywords`` endpoints. The
service is intentionally tiny: read overrides, write overrides, ensure
the profile exists.

Note (Phase 3 deviation): the persisted overrides are NOT yet honored by
the worker pipeline; the worker still loads its Settings via the layered
file/env loader. Wiring overrides through into ``ConfigSnapshot`` is a
Phase 5+ task once the AI/Evidence pipeline is in place.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...config import Settings
from ...core.models import DEFAULT_PROFILE_NAME, ConfigProfile
from ...core.run_key import compute_config_snapshot_hash
from ...storage.db import SqlConfigProfileRepository
from ..schemas.config import SettingsView


def current_settings_view(settings: Settings) -> SettingsView:
    """Project the loaded ``Settings`` into the public-facing view shape."""
    return SettingsView(
        pipeline_version=settings.runtime.pipeline_version,
        ai_backend=settings.ai.backend,
        ai_mode=settings.ai.mode,
        ocr_backend=settings.ocr.backend,
        ocr_languages=list(settings.ocr.languages),
        splitter_keyword_weight=settings.splitter.keyword_weight,
        splitter_layout_weight=settings.splitter.layout_weight,
        splitter_page_number_weight=settings.splitter.page_number_weight,
        splitter_auto_export_threshold=settings.splitter.auto_export_threshold,
        splitter_min_pages_per_part=settings.splitter.min_pages_per_part,
        archive_after_export=settings.exporter.archive_after_export,
    )


class ConfigService:
    """Read/write the persisted UI overrides profile."""

    def __init__(self, session: Session) -> None:
        self._profiles = SqlConfigProfileRepository(session)

    def ensure_default_profile(self) -> ConfigProfile:
        existing = self._profiles.get_by_name(DEFAULT_PROFILE_NAME)
        if existing is not None:
            return existing
        empty = ConfigProfile(
            name=DEFAULT_PROFILE_NAME,
            json_blob={},
            hash=compute_config_snapshot_hash({}),
        )
        return self._profiles.upsert_default(empty)

    def get_overrides(self) -> tuple[dict[str, Any], str]:
        profile = self.ensure_default_profile()
        return dict(profile.json_blob), profile.hash

    def set_overrides(self, overrides: dict[str, Any]) -> tuple[dict[str, Any], str]:
        cleaned = {k: v for k, v in overrides.items() if v is not None}
        profile_hash = compute_config_snapshot_hash(cleaned)
        saved = self._profiles.upsert_default(
            ConfigProfile(
                name=DEFAULT_PROFILE_NAME,
                json_blob=cleaned,
                hash=profile_hash,
            )
        )
        return dict(saved.json_blob), saved.hash
