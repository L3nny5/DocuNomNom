"""DTOs for the /config and /config/keywords endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...core.models import AiBackend, AiMode, OcrBackend


class SettingsView(BaseModel):
    """Effective settings as seen by the API.

    Includes only the slots the operator can adjust through the UI in
    Phase 3. Other Settings sections (paths, storage URL, worker timing)
    are intentionally read-only here because changing them at runtime is
    a deployment concern handled by the entrypoint, not by the UI.
    """

    model_config = ConfigDict(extra="forbid")

    pipeline_version: str
    ai_backend: AiBackend
    ai_mode: AiMode
    ocr_backend: OcrBackend
    ocr_languages: list[str] = Field(default_factory=list)
    splitter_keyword_weight: float = Field(ge=0.0, le=1.0)
    splitter_layout_weight: float = Field(ge=0.0, le=1.0)
    splitter_page_number_weight: float = Field(ge=0.0, le=1.0)
    splitter_auto_export_threshold: float = Field(ge=0.0, le=1.0)
    splitter_min_pages_per_part: int = Field(ge=1)
    archive_after_export: bool


class ConfigOverridesIn(BaseModel):
    """User-supplied overrides persisted in ``config_profiles``.

    All fields are optional. Submitted overrides replace the persisted
    payload (PUT semantics); unset fields drop back to file/env defaults.
    Phase 3 does not yet wire these into the worker pipeline (the worker
    still loads its own Settings); the persistence is real but inert,
    documented as a Phase 5+ wire-through.
    """

    model_config = ConfigDict(extra="forbid")

    ai_backend: AiBackend | None = None
    ai_mode: AiMode | None = None
    ocr_backend: OcrBackend | None = None
    ocr_languages: list[str] | None = None
    splitter_keyword_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    splitter_layout_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    splitter_page_number_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    splitter_auto_export_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    splitter_min_pages_per_part: int | None = Field(default=None, ge=1)
    archive_after_export: bool | None = None


class ConfigResponse(BaseModel):
    """GET /config payload."""

    settings: SettingsView
    overrides: dict[str, Any] = Field(default_factory=dict)
    overrides_hash: str = ""


class KeywordOut(BaseModel):
    """A keyword as returned to clients."""

    id: int
    term: str
    locale: str
    enabled: bool
    weight: float


class KeywordCreate(BaseModel):
    """Request body for POST /config/keywords."""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=255)
    locale: str = Field(default="en", min_length=2, max_length=8)
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class KeywordUpdate(BaseModel):
    """Request body for PUT /config/keywords/{id}."""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=255)
    locale: str = Field(min_length=2, max_length=8)
    enabled: bool
    weight: float = Field(ge=0.0, le=10.0)
