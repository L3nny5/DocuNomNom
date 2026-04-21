# Architecture

This document describes the v1 system as actually implemented. The
binding architectural baseline (modes, data model, scope guardrails)
remains the v1 plan; this file is the operator-facing summary.

## High-level pipeline

```
input PDFs
  -> Stability Watcher (file_sha256, pipeline_version, run_key)
  -> DB Job Queue (lease + heartbeat + crash recovery)
  -> Worker
       -> OcrPort (OCRmyPDF | Generic External API)
       -> Feature extractor (keywords, layout breaks, page numbers)
       -> Rule-based splitter -> ProposalDrafts + PartConfidence
       -> AiSplitPort (none | ollama | openai)
       -> Evidence Validator (mandatory gate)
       -> AI apply use case  -> ResolvedProposals
       -> Confidence aggregator -> DocumentPartDecision
       -> Atomic Exporter (work-dir -> rename(2) -> output dir)
       -> Archiver (originals)
       -> uncertain parts kept for the visual Review workflow
```

The flow is conservative by design: a missing OCR backend, an empty AI
output, a validator rejection, or a low-confidence boundary all route to
review rather than producing a half-baked split.

## Layer boundaries

Enforced by `import-linter` (`backend/.importlinter`):

- `core` may not depend on `api`, `adapters`, `storage`, `worker`, or
  `runtime`.
- `adapters` may not depend on `api`, `worker`, or `runtime`.
- `storage` may not depend on `api`, `worker`, or `runtime`.

`api`, `worker`, and `runtime` are composition roots. They may import
from `core`, `adapters`, `storage`, and `config`.

## Module ownership

| Module                                | Phase introduced |
| ------------------------------------- | ---------------- |
| `core/ports`, `core/models`           | Phase 1          |
| `core/usecases/transition_job`        | Phase 1          |
| `core/rules`, `core/confidence`       | Phase 2          |
| `core/evidence`                       | Phase 5          |
| `core/usecases/ai_split`              | Phase 5          |
| `core/usecases/review`                | Phase 4          |
| `adapters/ocr/ocrmypdf`               | Phase 2          |
| `adapters/ocr/generic_api`            | Phase 2          |
| `adapters/ai_split/{none,ollama,openai}` | Phase 5       |
| `adapters/pdf`, `adapters/clock`      | Phase 1 / 2      |
| `storage/db`, `storage/migrations`    | Phase 1          |
| `storage/files/safe_path`             | Phase 1          |
| `storage/files/atomic`                | Phase 2          |
| `worker/loop`, `worker/watcher`       | Phase 1          |
| `worker/processor`                    | Phase 2          |
| `worker/ai_factory`, `worker/ocr_factory` | Phase 2 / 5  |
| `api/routers/{health,jobs,history,config,keywords,review}` | Phase 3 / 4 |
| `runtime/preflight`, `runtime/logging` | Phase 6         |

## v1 invariants

The runtime preflight (`docunomnom.runtime.preflight`) refuses to start
when any of these are violated:

1. All four data dirs (`input`, `output`, `work`, `archive`) exist and
   are writable for the resolved UID.
2. `work_dir` and `output_dir` live on the same filesystem (so the
   exporter's `rename(2)` is atomic). Same for `work_dir` and
   `archive_dir` when `exporter.archive_after_export=true`.
3. The SQLite database file does not live on a remote / unsafe mount
   (NFS, CIFS/SMB, FUSE, sshfs, 9p). WAL guarantees do not hold there.
4. AI mode and backend are coherent: `mode != off` requires
   `backend != none`. `backend=openai` requires
   `network.allow_external_egress=true`, a non-empty
   `network.allowed_hosts`, and the `OPENAI_API_KEY` env var.
5. AI thresholds form a sane band:
   `auto_export_min_confidence >= review_required_below`.
6. Splitter weights sum to 1.0 (±0.01).
7. `runtime.pipeline_version` matches `MAJOR.MINOR.PATCH`.

In addition, the worker acquires an advisory PID-file lock at
`work_dir/.docunomnom_worker.lock`. A second worker started against the
same data directory refuses to boot.

## Persistence

- One SQLite database, WAL journal mode, `synchronous=NORMAL`,
  `busy_timeout=5000` ms, `foreign_keys=ON`.
- Schema migrations are applied automatically by the worker on startup
  via Alembic.
- Audit data (`job_events`, `split_decisions`, `evidences`) is the
  source of truth for "why did this split happen / get rejected".

## Atomic export

Per `core/storage/files/atomic.py`:

1. The OCR + analysis steps run inside `work_dir` and are fully
   `fsync(2)`'d.
2. The final part PDF is written under `work_dir`, then `rename(2)`'d
   into `output_dir`. `rename(2)` on the same filesystem is atomic, so
   paperless-ngx never sees a half-written PDF.
3. After successful export, the original is moved into `archive_dir`
   (also via `rename(2)` on the same filesystem).

## AI split modes

Implemented exactly per the plan; enforced by the Evidence Validator.

| Mode      | Allowed actions                              |
| --------- | -------------------------------------------- |
| off       | (no AI calls)                                |
| validate  | confirm, reject                              |
| refine    | confirm, reject, merge, adjust (bounded)     |
| enhance   | confirm, reject, merge, adjust, add          |

`refine` enforces `max_boundary_shift_pages`, adjacent-only `merge`,
and `max_changes_per_analysis`. `add` proposals require evidence on the
proposed page.
