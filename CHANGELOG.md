# Changelog

All notable changes to DocuNomNom are recorded here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/).

## [1.0.0] — v1 release

First usable v1. Everything below is in scope; everything not listed
here is intentionally out of scope (see `docs/limitations.md`).

### Added

- Watcher → DB job queue → single worker with lease/heartbeat/crash
  recovery (Phase 1).
- OCRmyPDF (Tesseract eng + deu) and generic external OCR API
  adapters (Phase 2).
- Conservative rule-based splitter, confidence aggregator, atomic
  exporter (work-dir → fsync → rename(2) → output-dir), archiver
  (Phase 2).
- Operator-facing API: jobs, history, config, keywords (Phase 3).
- Minimal visual review workflow: list, detail, PDF view, marker
  set/remove, finalize, reopen-from-history (Phase 4).
- AI split adapters: `none`, `ollama`, `openai`. Modes: `off`,
  `validate`, `refine`, `enhance`. Mandatory Evidence Validator gate
  (Phase 5).
- Phase 6 hardening:
  - `docunomnom.runtime.preflight` — startup-time validation of
    paths, same-filesystem requirements, SQLite mount type, AI/network
    coherence, threshold band, splitter weight sum, pipeline version.
  - `docunomnom.runtime.preflight.acquire_single_worker_lock` — PID
    file under `work_dir` enforcing the single-worker invariant.
  - `docunomnom.runtime.logging.configure_logging` — text/JSON
    structured logging with a stable operational event vocabulary
    (`LogEvent`).
  - Tini as PID 1, image-level HEALTHCHECK, OCI labels, named volume
    declarations.
  - Docs: architecture, API, operations runbook, configuration,
    backups, TrueNAS deployment, limitations.
  - Regression suite: split edges, no-partial-output exporter
    invariants, run_key byte-stability.
- v1 versioning: `docunomnom` 1.0.0 (Python), `docunomnom-frontend`
  1.0.0, image label `1.0.0`.

### Changed

- API title/version reported as 1.0.0; OpenAPI at `/api/v1/openapi.json`.
- Worker startup banner now uses the structured event names; the legacy
  free-text "DocuNomNom worker starting (Phase 2)" line is gone.
- Entrypoint hands signal handling off to tini and defers
  filesystem-type checks to the Python preflight.

### Hard guardrails (will refuse to start)

- Any of `input_dir`, `output_dir`, `work_dir`, `archive_dir` missing
  or unwritable.
- Cross-filesystem `work_dir` ↔ `output_dir` (or `archive_dir`).
- SQLite database on NFS / SMB / FUSE / sshfs / 9p.
- AI mode without backend, OpenAI without egress allow-list, OpenAI
  without `OPENAI_API_KEY`, inverted threshold band, splitter weights
  not summing to 1.0, malformed `pipeline_version`.
- A second worker against the same `work_dir`.

### Out of scope (and staying out for v1)

- Websocket / server-push.
- Multi-user auth / RBAC.
- Horizontal scaling beyond one worker.
- Drag-and-drop reordering or rich annotation tooling in review.
- Provider-specific OCR/AI adapters beyond what is shipped.

## [0.x] — pre-release

Phases 0 through 5 were tracked in branch / phase notes; they roll up
into 1.0.0 above. No public 0.x tags were cut.
