"""Application settings (layered config).

Layering, in order of decreasing precedence (plan §10):

1. Environment variables (``DOCUNOMNOM_*`` and ``DOCUNOMNOM__SECTION__KEY``).
2. YAML file pointed to by ``DOCUNOMNOM_CONFIG`` (or the bundled
   ``defaults.yaml`` next to this module if the env var is unset).
3. Code defaults declared on the model.

Phase 2 adds ``ocr``, ``network``, ``splitter``, and ``exporter`` sections.
UI-driven overrides (the topmost layer in plan §10) remain unimplemented;
they require the review/settings UI which lands in Phase 3+.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from ..core.models import AiBackend, AiMode, OcrBackend

PIPELINE_VERSION_DEFAULT = "1.0.0"

DEFAULTS_YAML_NAME = "defaults.yaml"


def _coerce_tuple(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    return value


class IngestionSettings(BaseModel):
    """Watcher / file-ingestion settings."""

    poll_interval_seconds: float = Field(default=5.0, ge=0.1)
    stability_window_seconds: float = Field(default=10.0, ge=0.0)
    ignore_patterns: tuple[str, ...] = Field(
        default=(".*", "*.partial", "*.crdownload", "*.tmp", "*.part")
    )
    require_pdf_magic: bool = True

    @field_validator("ignore_patterns", mode="before")
    @classmethod
    def _coerce_patterns(cls, value: Any) -> Any:
        return _coerce_tuple(value)


class StorageSettings(BaseModel):
    """Persistence settings (SQLite for v1)."""

    database_url: str = "sqlite:///./data/docunomnom.sqlite3"
    ocr_artifact_dir: str = "/data/work/ocr-artifacts"
    page_text_inline_max_bytes: int = Field(default=64_000, ge=0)


class PathSettings(BaseModel):
    """Filesystem mount points. Strings here are not yet resolved; the
    entrypoint validates them at startup."""

    input_dir: str = "/data/input"
    output_dir: str = "/data/output"
    work_dir: str = "/data/work"
    archive_dir: str = "/data/archive"


class WorkerSettings(BaseModel):
    """Worker loop settings."""

    poll_interval_seconds: float = Field(default=2.0, ge=0.1)
    lease_ttl_seconds: float = Field(default=120.0, ge=1.0)
    heartbeat_interval_seconds: float = Field(default=30.0, ge=0.1)
    max_attempts: int = Field(default=3, ge=1)


class OcrmypdfSettings(BaseModel):
    """Local OCR via OCRmyPDF."""

    clean_before_ocr: bool = True
    deskew: bool = True
    rotate_pages: bool = True
    skip_text: bool = True
    optimize: int = Field(default=1, ge=0, le=3)
    jobs: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=900.0, ge=1.0)


class ExternalOcrApiSettings(BaseModel):
    """Generic external OCR API.

    The adapter is intentionally provider-agnostic: it speaks one canonical
    request/response shape. Provider-specific adapters can be added in later
    phases by wrapping/translating to/from this contract.
    """

    endpoint: str = ""
    api_key: str = ""
    timeout_seconds: float = Field(default=120.0, ge=1.0)
    max_retries: int = Field(default=3, ge=0)
    backoff_base_seconds: float = Field(default=1.0, ge=0.0)
    backoff_max_seconds: float = Field(default=30.0, ge=0.0)
    max_payload_mb: float = Field(default=50.0, ge=0.1)
    page_chunk_size: int = Field(default=20, ge=1)
    require_https: bool = True


class OcrSettings(BaseModel):
    backend: OcrBackend = OcrBackend.OCRMYPDF
    languages: tuple[str, ...] = ("eng", "deu")
    ocrmypdf: OcrmypdfSettings = OcrmypdfSettings()
    external_api: ExternalOcrApiSettings = ExternalOcrApiSettings()

    @field_validator("languages", mode="before")
    @classmethod
    def _coerce_languages(cls, value: Any) -> Any:
        return _coerce_tuple(value)


class NetworkSettings(BaseModel):
    """External egress controls (plan §17)."""

    allow_external_egress: bool = False
    allowed_hosts: tuple[str, ...] = ()

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _coerce_hosts(cls, value: Any) -> Any:
        return _coerce_tuple(value)


class SplitterSettings(BaseModel):
    """Rule-based splitter knobs (plan §11)."""

    min_pages_per_part: int = Field(default=1, ge=1)
    keyword_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    layout_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    page_number_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    auto_export_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    keywords: tuple[str, ...] = (
        # Conservative defaults that bias toward under-splitting.
        "Rechnung",
        "Invoice",
        "Vertrag",
        "Contract",
        "Kontoauszug",
        "Account Statement",
        "Lohnabrechnung",
        "Payslip",
        "Mahnung",
        "Reminder",
    )

    @field_validator("keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, value: Any) -> Any:
        return _coerce_tuple(value)


class ExporterSettings(BaseModel):
    """Atomic exporter behavior (plan §15)."""

    archive_after_export: bool = True
    require_same_filesystem: bool = True
    output_basename_template: str = "{stem}_part_{index:03d}.pdf"
    review_all_splits: bool = False  # Not honored until review UI exists.


class OllamaSettings(BaseModel):
    """Ollama HTTP backend (local-friendly LLM)."""

    base_url: str = "http://ollama:11434"
    model: str = "qwen2.5:14b-instruct"
    timeout_seconds: float = Field(default=120.0, ge=1.0)


class OpenAISettings(BaseModel):
    """OpenAI-compatible HTTP backend.

    The actual API key is read from the environment via ``api_key_env``;
    we intentionally never persist the secret in YAML or DB.
    """

    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = Field(default=60.0, ge=1.0)


class AiThresholdSettings(BaseModel):
    """Confidence thresholds applied after AI proposals are merged in."""

    auto_export_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    review_required_below: float = Field(default=0.70, ge=0.0, le=1.0)


class AiEvidenceSettings(BaseModel):
    """Evidence Validator knobs (plan §10/§12)."""

    require_for_ai: bool = True
    min_evidences_per_proposal: int = Field(default=1, ge=1)
    allowed_kinds: tuple[str, ...] = (
        "keyword",
        "layout_break",
        "sender_change",
        "page_number",
        "structural",
        "ocr_snippet",
    )

    @field_validator("allowed_kinds", mode="before")
    @classmethod
    def _coerce_kinds(cls, value: Any) -> Any:
        return _coerce_tuple(value)


class AiRefineSettings(BaseModel):
    """Conservative bounds for ``refine`` mode (plan §11)."""

    max_boundary_shift_pages: int = Field(default=1, ge=0)
    max_changes_per_analysis: int = Field(default=3, ge=0)


class AiSettings(BaseModel):
    """AI configuration.

    Phase 5 wires this through into the worker pipeline. ``backend=none``
    (default) keeps the rule-only flow byte-for-byte deterministic.
    """

    backend: AiBackend = AiBackend.NONE
    mode: AiMode = AiMode.OFF
    ollama: OllamaSettings = OllamaSettings()
    openai: OpenAISettings = OpenAISettings()
    thresholds: AiThresholdSettings = AiThresholdSettings()
    evidence: AiEvidenceSettings = AiEvidenceSettings()
    refine: AiRefineSettings = AiRefineSettings()


class RuntimeSettings(BaseModel):
    pipeline_version: str = PIPELINE_VERSION_DEFAULT


def _yaml_settings_source(settings_cls: type[BaseSettings]) -> dict[str, Any]:
    """Load YAML file pointed to by ``DOCUNOMNOM_CONFIG``, else the bundled
    ``defaults.yaml`` next to this module."""
    import os

    path_env = os.environ.get("DOCUNOMNOM_CONFIG")
    yaml_path = Path(path_env) if path_env else Path(__file__).parent / DEFAULTS_YAML_NAME
    if not yaml_path.exists():
        return {}
    with yaml_path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML config root must be a mapping, got {type(loaded).__name__}")
    return loaded


class _YamlConfigSource(PydanticBaseSettingsSource):
    """pydantic-settings source that reads from the YAML layer."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = _yaml_settings_source(settings_cls)

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        value = self._data.get(field_name, ...)
        return value, field_name, value is not ...

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if v is not ...}


# Env-var convention documented above: ``DOCUNOMNOM__SECTION__KEY`` (double
# underscore after the prefix, double underscore between section and key).
# pydantic-settings' built-in env source, with ``env_prefix='DOCUNOMNOM_'``
# and ``env_nested_delimiter='__'``, actually matches
# ``DOCUNOMNOM_SECTION__KEY`` (single underscore after the prefix), which
# is a different shape. The double-underscore-after-prefix form is what
# the deploy configs (``compose.truenas.yaml`` and the production docker
# stack) use and what operators are documented to set, so we honor it
# here via an extra source. The built-in env source is preserved so the
# single-underscore form keeps working too.
_DOUBLE_UNDERSCORE_PREFIX = "DOCUNOMNOM__"


def _parse_double_underscore_env(env: dict[str, str]) -> dict[str, Any]:
    """Parse ``DOCUNOMNOM__SECTION__KEY=value`` entries into a nested
    dict ``{'section': {'key': value}}`` suitable as a settings source.

    Matching is case-insensitive to mirror ``case_sensitive=False`` on
    the ``Settings`` model. Keys that do not start with the double-
    underscore prefix are ignored; they belong to the regular
    single-underscore env source.
    """
    out: dict[str, Any] = {}
    for raw_key, raw_value in env.items():
        if not raw_key.upper().startswith(_DOUBLE_UNDERSCORE_PREFIX):
            continue
        body = raw_key[len(_DOUBLE_UNDERSCORE_PREFIX) :]
        if not body:
            continue
        parts = [p for p in body.split("__") if p]
        if not parts:
            continue
        cursor: dict[str, Any] = out
        for part in parts[:-1]:
            key = part.lower()
            existing = cursor.get(key)
            if not isinstance(existing, dict):
                existing = {}
                cursor[key] = existing
            cursor = existing
        cursor[parts[-1].lower()] = raw_value
    return out


class _DoubleUnderscoreEnvSource(PydanticBaseSettingsSource):
    """Settings source that reads ``DOCUNOMNOM__SECTION__KEY`` env vars.

    Complements the built-in env source (which handles ``DOCUNOMNOM_*``
    top-level vars) so both conventions documented at the top of this
    module resolve correctly. Runs at env-level precedence so the
    ``sqlite:////data/...`` URL set in the production compose file wins
    over the YAML layer, matching what operators expect.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        import os

        self._data: dict[str, Any] = _parse_double_underscore_env(dict(os.environ))

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        value = self._data.get(field_name, ...)
        return value, field_name, value is not ...

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


class Settings(BaseSettings):
    """Top-level settings.

    Precedence (highest first): env vars > YAML file > model defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="DOCUNOMNOM_",
        env_nested_delimiter="__",
        env_file=None,
        case_sensitive=False,
    )

    log_level: str = "INFO"

    paths: PathSettings = PathSettings()
    storage: StorageSettings = StorageSettings()
    ingestion: IngestionSettings = IngestionSettings()
    worker: WorkerSettings = WorkerSettings()
    ocr: OcrSettings = OcrSettings()
    network: NetworkSettings = NetworkSettings()
    splitter: SplitterSettings = SplitterSettings()
    exporter: ExporterSettings = ExporterSettings()
    ai: AiSettings = AiSettings()
    runtime: RuntimeSettings = RuntimeSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Order = precedence (first source wins). The double-underscore
        # env source sits at env-level precedence alongside the built-in
        # one: both override YAML, neither overrides explicit init args.
        return (
            init_settings,
            env_settings,
            _DoubleUnderscoreEnvSource(settings_cls),
            _YamlConfigSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached ``Settings`` instance. Useful for tests that mutate
    environment variables between cases."""
    get_settings.cache_clear()
