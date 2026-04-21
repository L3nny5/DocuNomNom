# Configuration

DocuNomNom uses a layered configuration model. Sources, in order of
decreasing precedence:

1. Environment variables (`DOCUNOMNOM_*`, nested via `__`).
2. The YAML file pointed to by `DOCUNOMNOM_CONFIG`, if set.
3. The bundled `defaults.yaml` next to the settings module.
4. Model defaults declared in `config/settings.py`.

## UI vs. ENV/YAML surfaces

The REST `/config` endpoint (and its UI) only exposes the subset of
settings that are safe to change at runtime without redeploying the
container. Deployment-level concerns — filesystem paths, database
URLs, network egress policy, secrets — intentionally live only in
ENV/YAML.

| Section                                       | UI | ENV/YAML |
| --------------------------------------------- | :-: | :-: |
| `paths.*`                                     |    | ✔ |
| `storage.*`                                   |    | ✔ |
| `network.*`                                   |    | ✔ |
| `ocr.backend`, `ocr.languages`                | ✔ | ✔ |
| `ocr.ocrmypdf.*`, `ocr.external_api.*`        |    | ✔ |
| `ai.backend`, `ai.mode`                       | ✔ | ✔ |
| `ai.ollama.*`, `ai.openai.*`                  |    | ✔ |
| `ai.thresholds`, `ai.evidence`, `ai.refine`   |    | ✔ |
| `splitter` weights + `auto_export_threshold`  | ✔ | ✔ |
| `splitter.min_pages_per_part`                 | ✔ | ✔ |
| `exporter.archive_after_export`               | ✔ | ✔ |
| Keywords (term / locale / enabled / weight)   | ✔ | ✔ |
| `worker.*`, `ingestion.*`, `runtime.*`        |    | ✔ |
| Logging (`DOCUNOMNOM_LOG_LEVEL`, `_LOG_FORMAT`) |    | ✔ |

UI overrides are persisted in the `config_profiles` table. v1 does
not yet wire every override back into the worker pipeline — treat
**keywords** and **splitter weights / thresholds** as the primary
live-tunable surfaces, and ENV/YAML as the source of truth for
everything else.

## Environment variable mapping

The env prefix is `DOCUNOMNOM_`. Nested fields use a double underscore:

```
DOCUNOMNOM__PATHS__INPUT_DIR=/data/input
DOCUNOMNOM__AI__BACKEND=openai
DOCUNOMNOM__AI__MODE=validate
DOCUNOMNOM__NETWORK__ALLOW_EXTERNAL_EGRESS=true
DOCUNOMNOM__NETWORK__ALLOWED_HOSTS=["api.openai.com"]
```

Lists must be JSON-encoded when passed via env vars.

## Sections

### `paths`

| Key            | Default                | Notes                                       |
| -------------- | ---------------------- | ------------------------------------------- |
| `input_dir`    | `/data/input`          | Watched for incoming PDFs.                  |
| `output_dir`   | `/data/output`         | paperless-ngx consume target. Same fs as work. |
| `work_dir`     | `/data/work`           | Atomic staging. Same fs as output + archive.|
| `archive_dir`  | `/data/archive`        | Originals after successful export.          |

### `storage`

| Key                          | Default                              |
| ---------------------------- | ------------------------------------ |
| `database_url`               | `sqlite:///./data/docunomnom.sqlite3` |
| `ocr_artifact_dir`           | `/data/work/ocr-artifacts`           |
| `page_text_inline_max_bytes` | `64000`                              |

The DB file MUST live on a local filesystem (ext4 / xfs / zfs / btrfs).
Remote mounts (NFS, CIFS, FUSE, sshfs) are rejected by preflight.

### `ingestion`

Watcher knobs: `poll_interval_seconds`, `stability_window_seconds`,
`ignore_patterns`, `require_pdf_magic` (default `true`).

### `worker`

Queue knobs: `poll_interval_seconds`, `lease_ttl_seconds`,
`heartbeat_interval_seconds`, `max_attempts`.

### `ocr`

| Key             | Default                                |
| --------------- | -------------------------------------- |
| `backend`       | `ocrmypdf`                             |
| `languages`     | `["eng", "deu"]`                       |
| `ocrmypdf.*`    | deskew, rotate_pages, optimize, jobs, timeout |
| `external_api.*` | endpoint, api_key, retries, https-required, payload caps |

Backend requirements:

- `ocrmypdf` — the `ocrmypdf` Python package must be importable from
  the worker's interpreter. The published image installs it via the
  `docunomnom[ocr]` extra alongside system binaries (tesseract,
  ghostscript, unpaper, qpdf, pngquant). Preflight check
  `ocr.backend_available` fails at boot if it isn't importable (see
  the troubleshooting note below).
- `external_api` — `ocr.external_api.endpoint` must be set and
  reachable. For non-localhost endpoints you also need
  `network.allow_external_egress=true` and the host in
  `network.allowed_hosts`. HTTPS is required unless
  `ocr.external_api.allow_http=true` (discouraged).

Troubleshooting:

> `ocr_config_error: ocrmypdf is not installed but the OCRmyPDF
> backend was selected`
>
> The `ocrmypdf` Python module is not on the worker interpreter's
> import path. Use the published image, or if you build your own
> image make sure `pip install 'docunomnom[ocr]'` runs inside the
> final image. The Debian `ocrmypdf` apt package alone is not
> sufficient when the container's Python differs from the system
> Python (e.g. the `python:3.12-slim-bookworm` base). From v1.0.x
> this is caught at boot by the `ocr.backend_available` preflight
> check instead of failing on the first job.

### `network`

| Key                     | Default | Notes                                       |
| ----------------------- | ------- | ------------------------------------------- |
| `allow_external_egress` | `false` | Required for OpenAI + external OCR API.     |
| `allowed_hosts`         | `[]`    | Allow-list; empty means no external calls.  |

### `splitter`

Weights MUST sum to 1.0 (preflight enforces ±0.01):

```yaml
splitter:
  keyword_weight: 0.6
  layout_weight: 0.2
  page_number_weight: 0.2
  auto_export_threshold: 0.65
  min_pages_per_part: 1
  keywords:
    - Rechnung
    - Invoice
```

### `exporter`

| Key                       | Default | Notes                                            |
| ------------------------- | ------- | ------------------------------------------------ |
| `archive_after_export`    | `true`  | Move originals into `archive_dir` after success. |
| `require_same_filesystem` | `true`  | Reject cross-device renames at preflight.        |
| `output_basename_template`| `{stem}_part_{index:03d}.pdf` |                                  |

### `ai`

```yaml
ai:
  backend: none           # none | ollama | openai
  mode: off               # off | validate | refine | enhance
  ollama:
    base_url: http://ollama:11434
    model: qwen2.5:14b-instruct
    timeout_seconds: 120
  openai:
    api_key_env: OPENAI_API_KEY    # the secret stays in env, never YAML
    base_url: https://api.openai.com
    model: gpt-4o-mini
    timeout_seconds: 60
  thresholds:
    auto_export_min_confidence: 0.85
    review_required_below: 0.70
  evidence:
    require_for_ai: true
    min_evidences_per_proposal: 1
    allowed_kinds: [keyword, layout_break, sender_change, page_number, structural, ocr_snippet]
  refine:
    max_boundary_shift_pages: 1
    max_changes_per_analysis: 3
```

Coherence rules (preflight):

- `mode != off` requires `backend != none`.
- `backend = openai` requires `network.allow_external_egress=true`,
  a non-empty `network.allowed_hosts`, and the env var named in
  `ai.openai.api_key_env`.
- `auto_export_min_confidence >= review_required_below`.

### `runtime`

| Key                | Default | Notes                                              |
| ------------------ | ------- | -------------------------------------------------- |
| `pipeline_version` | `1.0.0` | Part of the `run_key`. Bumping it forces reprocessing of all files. |

### Logging

| Env var                    | Effect                                              |
| -------------------------- | --------------------------------------------------- |
| `DOCUNOMNOM_LOG_LEVEL`     | `DEBUG | INFO | WARNING | ERROR`. Default `INFO`.   |
| `DOCUNOMNOM_LOG_FORMAT`    | `text` (dev default) or `json` (container default). |
