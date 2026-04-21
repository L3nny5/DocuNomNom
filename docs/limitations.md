# Limitations & guardrails (v1)

DocuNomNom v1 is intentionally narrow. This document is the operator
contract: what the system does, what it deliberately does not do, and
what an upgrade beyond v1 would entail.

## In scope (v1)

- Watch a single input directory, OCR with OCRmyPDF (Tesseract eng+deu)
  or a generic external OCR API, conservatively split, atomically
  export safe parts to one output directory, archive originals.
- AI split adapters: `none`, `ollama`, `openai`. Modes: `off`,
  `validate`, `refine`, `enhance`.
- Mandatory Evidence Validator before any AI proposal influences
  splits.
- Visual review workflow for uncertain parts: PDF display, marker
  set/remove, finalize, reopen from history.
- Single-process worker model on SQLite with WAL.
- TrueNAS / docker-compose deployment.

## Hard guardrails (enforced)

- Single worker. Multiple workers are refused via PID-file lock.
- All four data directories on the same local filesystem.
- SQLite database not on NFS / SMB / FUSE.
- AI mode/backend/network coherence (see `architecture.md`).
- Splitter weights sum to 1.0.
- AI thresholds form a sane band.
- `pipeline_version` matches `MAJOR.MINOR.PATCH`.

Failures of any of the above stop the worker on startup with an
operator-readable message — by design. The system will not start in a
half-safe configuration.

## Conservative defaults

- AI is `off` by default. The deterministic rule-based flow is the
  baseline; AI only ever adjusts proposals once enabled and validated.
- `auto_export_threshold` and AI `auto_export_min_confidence` favor
  routing borderline cases to manual review rather than auto-export.
- The exporter never overwrites a file in `output_dir`; collisions get
  a numeric suffix.
- The worker never deletes from `input_dir` until it has successfully
  archived (or processed) the original.

## Out of scope (v1)

- Websocket / server-push. The UI polls.
- Authentication / multi-user / RBAC. v1 trusts the network boundary.
- Drag-and-drop reordering or rich annotation tooling in the review UI.
- Provider-specific OCR adapters beyond OCRmyPDF and the generic
  external API.
- Provider-specific AI adapters beyond `none`, `ollama`, `openai`.
- Horizontal scaling. SQLite + single worker is the v1 contract.
- Multi-tenant data partitioning.
- A dedicated metrics endpoint (`/metrics`). v1 relies on structured
  logs and the persisted `job_events` audit trail.
- A first-class plugin system.

## Known limitations

- OCR quality depends on Tesseract. Severely degraded scans may
  produce empty text and trigger review-required outcomes.
- The validator can only check evidence kinds the rest of the
  pipeline already extracts. `sender_change`, for example, is
  validated structurally but is not currently mined as a rule signal;
  it is supported for AI proposals only.
- Path resolution uses `Path.resolve(strict=False)`. Symlinks inside
  the data dirs are followed; do not place untrusted symlinks in
  `input_dir`.
- The advisory single-worker lock is just that — advisory. It catches
  honest misconfiguration, not deliberate abuse.

## When you outgrow v1

Indicators it is time to plan a v2:

- More than one worker is needed for throughput.
- The DB needs to live on a remote / shared filesystem.
- You need RBAC / multi-tenant isolation in the API layer.
- You need real-time UI updates instead of polling.

These are deliberate v1 boundaries; pushing past them is a
v2-architecture concern, not a configuration toggle.
