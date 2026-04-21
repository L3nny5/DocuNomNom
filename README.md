# DocuNomNom

DocuNomNom is a Dockerized PDF auto-splitting service for TrueNAS and
other Linux hosts. It watches a mounted input directory for PDFs, runs
OCR, conservatively detects document boundaries (deterministic rules
plus optional AI), and atomically exports only safe parts into a
paperless-ngx consume directory. Anything uncertain waits in a visual
manual-review workflow.

> **Status: v1.0.x — first usable release.** TrueNAS/compose readiness,
> operational documentation, and regression suite are complete. See
> [`CHANGELOG.md`](CHANGELOG.md) for capabilities and
> [`docs/limitations.md`](docs/limitations.md) for what is intentionally
> out of scope.

---

## What DocuNomNom does

1. **Watch** — stability-gated watcher under `input_dir` picks up PDFs
   whose size stops changing.
2. **OCR** — runs either OCRmyPDF locally or a generic external OCR
   HTTP API, depending on `ocr.backend`.
3. **Feature-extract + rule-split** — deterministic keyword / layout /
   page-number signals produce a base split proposal with explicit
   evidence.
4. **AI (optional)** — `validate`, `refine`, or `enhance` the rule
   proposal via Ollama or OpenAI, guarded by an evidence validator and
   confidence thresholds.
5. **Atomic export** — safe parts are renamed into `output_dir`
   (paperless's consume directory). Originals move to `archive_dir`.
6. **Review** — uncertain parts land in the built-in review UI; an
   operator confirms, rejects, or reopens them.

Full pipeline diagram and module boundaries:
[`docs/architecture.md`](docs/architecture.md).

---

## How to run it

### Docker Compose

```bash
docker compose \
  -f deploy/docker/compose.yaml \
  -f deploy/docker/compose.truenas.yaml \
  up -d
```

Published images live at `ghcr.io/<this-repo>:latest` (also tagged by
commit SHA and semver). Pin a specific tag in production.

Then drop a PDF into `${INPUT_DIR}` and watch `${OUTPUT_DIR}`.

- **UI:** `http://<host>:8080/` — operator UI for jobs, history,
  review, keywords, and the runtime config surface.
- **API docs:** `http://<host>:8080/api/v1/docs`.

See [`docs/truenas.md`](docs/truenas.md) for the recommended dataset
layout and exact compose variables.

### Healthchecks

- `api`: `GET /api/v1/health` → `{"status":"ok"}`.
- `worker`: `test -f ${WORK_DIR}/.docunomnom_worker.lock`.

---

## Connecting to paperless-ngx

DocuNomNom hands finished split parts to paperless by dropping them
into paperless's own consume directory.

1. **Share the dataset / volume.** Point `OUTPUT_DIR` at paperless's
   `CONSUME_DIR`. Both services must see the same filesystem path.
2. **Match UID/GID.** Run paperless and the DocuNomNom worker under
   the same numeric UID (or a shared GID with permissive ACLs) so
   paperless can actually delete the consumed files after ingesting
   them.
3. **Same filesystem for `work_dir` → `output_dir`.** The exporter
   uses atomic `rename(2)`; cross-device renames are rejected by
   preflight. Keep `work_dir`, `output_dir`, and `archive_dir` on the
   same dataset.
4. **No extra "stable file" delay.** The atomic rename guarantees
   paperless never sees a half-written PDF.

Full step-by-step: [`docs/truenas.md`](docs/truenas.md).

---

## Configuration overview

DocuNomNom has three configuration surfaces, in decreasing order of
precedence:

| Source                     | Scope                                         | Change requires |
| -------------------------- | --------------------------------------------- | --------------- |
| Environment variables      | Deployment / secrets / paths / network policy | Container restart |
| `DOCUNOMNOM_CONFIG` YAML   | Baseline tuning checked into your infra repo | Container restart |
| UI (`/api/v1/config`)      | A small operator-facing subset — see below   | Live (stored as override; v1 wire-through is inert for most keys) |

Environment variables use the `DOCUNOMNOM_` prefix and double-underscore
nesting, for example:

```env
DOCUNOMNOM__PATHS__INPUT_DIR=/data/input
DOCUNOMNOM__STORAGE__DATABASE_URL=sqlite:////data/docunomnom.sqlite3
DOCUNOMNOM__OCR__BACKEND=ocrmypdf
DOCUNOMNOM__AI__BACKEND=openai
DOCUNOMNOM__AI__MODE=validate
DOCUNOMNOM__NETWORK__ALLOW_EXTERNAL_EGRESS=true
DOCUNOMNOM__NETWORK__ALLOWED_HOSTS=["api.openai.com"]
OPENAI_API_KEY=sk-...
```

Lists must be JSON-encoded when passed via env vars. The complete
reference lives in [`docs/configuration.md`](docs/configuration.md).

### What is UI-configurable vs ENV/YAML-only

The UI intentionally exposes only the knobs that are safe to flip at
runtime. Paths, database URLs, network policy, and secrets stay in
env/YAML so deployment semantics do not drift from the running
container.

| Setting                                       | UI | ENV/YAML |
| --------------------------------------------- | :-: | :-: |
| `paths.*` (input / output / work / archive)   |    | ✔ |
| `storage.database_url`, `storage.ocr_artifact_dir` |    | ✔ |
| `network.allow_external_egress`, `allowed_hosts` |    | ✔ |
| `ai.openai.api_key_env` + the referenced env var |    | ✔ |
| `ai.backend`, `ai.mode`                       | ✔ | ✔ |
| `ai.ollama.*`, `ai.openai.base_url` / `model` |    | ✔ |
| `ai.thresholds`, `ai.evidence`, `ai.refine`   |    | ✔ |
| `ocr.backend`, `ocr.languages`                | ✔ | ✔ |
| `ocr.ocrmypdf.*` tuning, `ocr.external_api.*` |    | ✔ |
| `splitter` weights + `auto_export_threshold`  | ✔ | ✔ |
| `splitter.min_pages_per_part`, `archive_after_export` | ✔ | ✔ |
| Keywords (per-term weights, enable/disable)   | ✔ | ✔ |
| `worker.*`, `ingestion.*` timing              |    | ✔ |
| Logging (`DOCUNOMNOM_LOG_LEVEL`, `_LOG_FORMAT`) |    | ✔ |

> Phase 3 caveat: UI overrides are persisted in the `config_profiles`
> table but the worker pipeline still reads its own Settings snapshot
> for OCR/AI backend selection. Treat the UI as the primary surface
> for **keywords** and **splitter weights**, and ENV/YAML as the
> source of truth for everything else until a later release wires the
> overrides through end-to-end.

---

## OCR configuration

Pick the backend with `DOCUNOMNOM__OCR__BACKEND` (or `ocr.backend` in
YAML). The worker refuses to boot if the selected backend is not
available — see the troubleshooting section below.

| Backend        | When to use it                                  | Required runtime | Required env |
| -------------- | ----------------------------------------------- | ---------------- | ------------ |
| `ocrmypdf`     | Default. Local OCR inside the container.        | Shipped in image: `ocrmypdf` (PyPI), Tesseract, Ghostscript, unpaper, qpdf, pngquant. | `ocr.languages` (default `["eng","deu"]`). Language packs `tesseract-ocr-eng` and `tesseract-ocr-deu` are preinstalled. |
| `external_api` | Offload OCR to a paperless-ngx-compatible HTTP service. | None (pure HTTP client). | `ocr.external_api.endpoint`, optional `ocr.external_api.api_key`, `network.allow_external_egress=true`, and the target host in `network.allowed_hosts`. |

Common OCRmyPDF knobs (`ocr.ocrmypdf.*`): `deskew`, `rotate_pages`,
`skip_text`, `optimize`, `jobs`, `timeout_seconds`. Full table:
[`docs/configuration.md`](docs/configuration.md).

---

## AI configuration

Two axes: **backend** (which provider to talk to) and **mode** (how
much agency the AI has in the pipeline).

| `ai.backend` | Connectivity                                              | Required env / YAML                                                                 |
| ------------ | --------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `none`       | AI is disabled. Rule splitter only.                       | —                                                                                   |
| `ollama`     | HTTP to a self-hosted Ollama (no external egress needed). | `ai.ollama.base_url`, `ai.ollama.model`. Host must be reachable from the container. |
| `openai`     | HTTPS to OpenAI or a compatible proxy.                    | `network.allow_external_egress=true`, `network.allowed_hosts` includes the API host, `ai.openai.api_key_env` points at an env var like `OPENAI_API_KEY` that is actually set. |

| `ai.mode`  | Effect on the pipeline                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------- |
| `off`      | AI is not called even if `backend != none`. Rule output wins.                                   |
| `validate` | AI confirms/denies the rule proposal. Disagreement drops the part into manual review.           |
| `refine`   | AI may shift boundaries by at most `ai.refine.max_boundary_shift_pages` and change at most `max_changes_per_analysis` points. Anything bigger requires review. |
| `enhance`  | AI may propose new boundaries. Evidence validator and thresholds are strictly enforced.         |

Coherence rules enforced at boot (preflight):

- `mode != off` requires `backend != none`.
- `backend = openai` requires egress + allow-list + the referenced API
  key env variable.
- `auto_export_min_confidence >= review_required_below`.

Full YAML example: [`docs/configuration.md`](docs/configuration.md).

---

## Operations

- **Single worker.** Enforced via advisory PID-file lock under
  `work_dir`. Stale locks after `kill -9` are reclaimed on next boot.
- **Preflight** (`docunomnom.runtime.preflight`) refuses to boot on
  wrong paths, DB on NFS/SMB/FUSE, mismatched filesystems between
  `work_dir`/`output_dir`, incoherent AI/network settings, OCR backend
  whose Python deps aren't importable, or splitter weights that don't
  sum to 1.0.
- **JSON logs** via `DOCUNOMNOM_LOG_FORMAT=json` (the container
  default). Stable event names in
  `docunomnom.runtime.logging.LogEvent`.
- **Backups.** Stop the worker, copy `${DATA_DIR}/docunomnom.sqlite3`,
  restart. Full procedure in [`docs/backups.md`](docs/backups.md).

Day-to-day runbook: [`docs/operations.md`](docs/operations.md).

---

## Troubleshooting

### `ocr_config_error: ocrmypdf is not installed but the OCRmyPDF backend was selected`

Root cause: the Python interpreter running the worker cannot import
the `ocrmypdf` module. The published image ships `ocrmypdf` as a PyPI
package installed into Python 3.12, but if you built your own image
relying on the Debian `ocrmypdf` apt package alone, that module is
installed under `/usr/lib/python3/dist-packages/` for the system
Python 3.11 and is invisible to Python 3.12.

Fix:

- Use the published image (`ghcr.io/<this-repo>:<tag>`), which
  installs `ocrmypdf` via `pip install 'docunomnom[ocr]'`.
- If you build your own image, add `ocrmypdf` to the `pip install`
  step (or use the `ocr` extra). Do not rely on the Debian
  `ocrmypdf` apt package when the container's Python differs from
  the system Python.
- If you only need HTTP OCR, switch to
  `DOCUNOMNOM__OCR__BACKEND=external_api` and set
  `ocr.external_api.endpoint`.

From v1.0.x the preflight check `ocr.backend_available` catches this
at boot with an operator-readable message instead of waiting for the
first job to fail.

### `worker.preflight.fail` on boot

Read the `detail=` field in the structured log line. Common triggers:

- `paths.*` unwritable or missing.
- `storage.database_url` points at an NFS/SMB/FUSE mount.
- `ai.mode != off` while `ai.backend = none`.
- `ai.backend = openai` without egress + allow-list + API key env
  variable.
- `splitter` weights don't sum to 1.0 (±0.01).

Fix the setting, restart.

### UI returns 404 for `/` or assets

The API is reachable at `/api/v1/*` but the SPA is missing. Either
the image was built without the frontend stage, or
`DOCUNOMNOM_FRONTEND_DIST` points at a directory that is missing
`index.html`. Use a published image or rebuild with the multi-stage
`deploy/docker/Dockerfile`.

### Jobs stuck in `running`

The worker was hard-killed mid-job. Wait `worker.lease_ttl_seconds`;
the queue's crash-recovery re-leases the job. If a job keeps failing,
inspect `job_events`, fix the root cause, and retry via
`POST /api/v1/jobs/{id}/retry`.

More failure modes and remedies:
[`docs/operations.md`](docs/operations.md).

---

## Local development

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ocr]"
ruff check .
ruff format --check .
mypy
lint-imports
pytest
uvicorn docunomnom.api.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run typecheck
npm run format
npm run test
npm run dev
```

Layers (strict hexagonal, enforced via `import-linter`):

- `core` — framework-free domain, use-cases, ports, rules, confidence,
  evidence.
- `adapters` — OCR / AI / HTTP / PDF adapters; never imports `api`,
  `worker`, or `runtime`.
- `storage` — SQLAlchemy models, repositories, migrations; never
  imports `api`, `worker`, or `runtime`.
- `api` — FastAPI routes, DTOs.
- `worker` — single DB-polling worker process.
- `runtime` — preflight + logging composition root.

---

## What v1 does not do

Short version; full list in [`docs/limitations.md`](docs/limitations.md).

- No websocket / server-push. The UI polls.
- No authentication / RBAC.
- No horizontal scaling beyond one worker.
- No OCR or AI providers beyond OCRmyPDF, the generic external OCR
  API, `none` / `ollama` / `openai`.

## License

Proprietary. See package metadata in `backend/pyproject.toml`.
