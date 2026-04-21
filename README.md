# DocuNomNom

DocuNomNom is a Dockerized PDF auto-splitting service for TrueNAS. It
watches a mounted input directory for PDFs, performs OCR, conservatively
detects document boundaries (deterministic rules + optional AI), and
atomically exports only safe split parts to a paperless-ngx consume
directory. Uncertain parts wait in a visual manual review workflow.

> **Status: v1.0.0 — first usable release.** Phase 6 hardening,
> TrueNAS/compose readiness, operational documentation, and regression
> suite are complete. See [`CHANGELOG.md`](CHANGELOG.md) for the full
> set of v1 capabilities and [`docs/limitations.md`](docs/limitations.md)
> for what is intentionally out of scope.

## High-level architecture (v1)

```
input PDFs -> Stability Watcher -> DB Job-Queue -> Worker
              -> OcrPort (OCRmyPDF | Generic External API)
              -> Feature Extractor -> Rule-Based Splitter
              -> AiSplitPort (off | validate | refine | enhance)
              -> Evidence Validator (mandatory gate)
              -> Confidence Aggregator
              -> Atomic Exporter -> paperless consume
              -> uncertain parts -> Review Service -> UI
```

Layers (strict hexagonal, enforced via `import-linter`):

- `core` — framework-free domain, use-cases, ports, rules, confidence,
  evidence.
- `adapters` — OCR / AI / HTTP / PDF adapters; never imports `api`,
  `worker`, or `runtime`.
- `storage` — SQLAlchemy models, repositories, migrations; never imports
  `api`, `worker`, or `runtime`.
- `api` — FastAPI routes, DTOs.
- `worker` — single DB-polling worker process.
- `runtime` — preflight + logging composition root.

The full architectural plan, modes, data model, and v1 scope guardrails
are the binding baseline; the implemented behavior is documented in
[`docs/architecture.md`](docs/architecture.md).

## Repository layout

```
backend/                 Python 3.12 + FastAPI service (api + worker share image)
frontend/                Vite + React + TypeScript UI
deploy/docker/           Dockerfile + compose (local + TrueNAS overlay)
deploy/scripts/          Container entrypoint
.github/workflows/       CI
docs/                    Architecture / API / operations / config / backups / TrueNAS / limitations
CHANGELOG.md             Release notes
```

## Quick start (Docker / TrueNAS)

```bash
docker compose \
  -f deploy/docker/compose.yaml \
  -f deploy/docker/compose.truenas.yaml \
  up -d --build
```

Then drop a PDF in `${INPUT_DIR}` and watch `${OUTPUT_DIR}` (paperless's
consume dir). Operator UI at <http://host:8080/api/v1/docs>.

See [`docs/truenas.md`](docs/truenas.md) for the recommended dataset
layout and [`docs/configuration.md`](docs/configuration.md) for the
full settings reference.

## Local development

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
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

## Operations

- Single-worker invariant. The worker enforces it via an advisory
  PID-file lock under `work_dir`.
- Startup preflight (`docunomnom.runtime.preflight`) refuses to boot
  when paths are wrong, the SQLite DB is on NFS/SMB/FUSE, the AI
  backend/network/threshold settings are incoherent, or the splitter
  weights do not sum to 1.0.
- Structured JSON logging via `DOCUNOMNOM_LOG_FORMAT=json`. Stable
  operational event names live in `docunomnom.runtime.logging.LogEvent`.
- Backups: stop worker, copy `${DATA_DIR}/docunomnom.sqlite3`, restart.
  See [`docs/backups.md`](docs/backups.md) for the full procedure.

Day-to-day operator runbook in [`docs/operations.md`](docs/operations.md).

## What v1 does not do

(Short version — see [`docs/limitations.md`](docs/limitations.md) for
the complete list.)

- No websocket / server-push. The UI polls.
- No authentication / RBAC.
- No horizontal scaling beyond one worker.
- No additional OCR or AI providers beyond OCRmyPDF, the generic
  external OCR API, `none` / `ollama` / `openai`.

## License

Proprietary. See package metadata in `backend/pyproject.toml`.
