# Configuration

DocuNomNom uses a layered configuration model. Sources, in order of
decreasing precedence:

1. Environment variables (`DOCUNOMNOM_*`, nested via `__`).
2. The YAML file pointed to by `DOCUNOMNOM_CONFIG`, if set.
3. The bundled `defaults.yaml` next to the settings module.
4. Model defaults declared in `config/settings.py`.

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
