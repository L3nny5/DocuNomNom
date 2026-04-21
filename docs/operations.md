# Operations runbook

Day-to-day operations of a v1 DocuNomNom deployment.

## Process model

- **api** — uvicorn HTTP server. Stateless; safe to restart any time.
- **worker** — single process. Picks up jobs from the SQLite-backed
  queue, runs OCR, splits, and exports. v1 invariant: exactly one
  worker. Enforced by an advisory PID-file lock under `work_dir`.

Both processes share one Docker image and one SQLite database file.
The worker performs schema migrations on startup; do not run Alembic
manually in production.

## Startup sequence (worker)

1. `configure_logging` reads `DOCUNOMNOM_LOG_LEVEL` and
   `DOCUNOMNOM_LOG_FORMAT` (`text` or `json`).
2. `run_preflight` validates paths, same-filesystem requirements,
   SQLite mount type, AI/network coherence, splitter weights, and
   `pipeline_version`. A failure exits with code `2` and an
   operator-readable error. See [`architecture.md`](architecture.md)
   for the full invariant list.
3. `acquire_single_worker_lock` writes a PID file under `work_dir`. A
   conflict exits with code `3`.
4. `run_alembic_upgrade` brings the DB schema to head.
5. The polling loop alternates a watcher scan and a queue drain.

## Healthchecks

- `api`: `GET /api/v1/health` returns `{"status":"ok"}`.
- `worker`: `test -f /data/work/.docunomnom_worker.lock` (lock file
  exists iff a worker is running and has not been killed -9).

## Logs

JSON output (`DOCUNOMNOM_LOG_FORMAT=json`, the container default) emits
single-line records with stable fields:

```
{"ts":"...","level":"INFO","logger":"docunomnom.worker","message":"worker.ready"}
```

Operational event names live under `docunomnom.runtime.logging.LogEvent`
(e.g. `worker.starting`, `worker.preflight.fail`, `job.failed`).
Per-job pipeline events are persisted to the `job_events` table —
look there first when you need a forensic trail.

Sensitive content (OCR text, AI responses) is intentionally NOT logged.
It lives in the database audit tables (and on disk under work/output)
where regular filesystem permissions and backups apply.

## Common operator tasks

### Re-run a failed job

```
POST /api/v1/jobs/{job_id}/retry
```

Re-queues the job with the same `run_key`.

### Reprocess from scratch

```
POST /api/v1/jobs/{job_id}/reprocess
```

Bumps the `run_key` so OCR + splitter run again. Useful after a config
change.

### Reopen an exported part for review

```
POST /api/v1/history/{part_id}/reopen
```

Creates a new review item; original audit history stays intact.

### Trigger a watcher rescan

```
POST /api/v1/jobs/rescan
```

Synchronous; returns the number of newly enqueued files.

## Failure modes and recovery

| Symptom                           | Cause                                                    | Action                                                                 |
| --------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------- |
| `worker.preflight.fail` on boot   | Misconfigured paths / mounts / AI                        | Read the `detail=` field; fix config; restart worker.                  |
| `worker.lock.denied` on boot      | A second worker process is already running               | Stop the duplicate; the lock self-heals on next boot.                  |
| Stale lock after `kill -9`        | Worker was hard-killed                                   | Boot will detect a dead PID and reclaim the lock automatically.        |
| Jobs stuck in `running`           | Worker crashed mid-job; lease hasn't expired yet         | Wait `worker.lease_ttl_seconds`; queue's crash-recovery re-leases.     |
| Same job keeps failing            | Hit `worker.max_attempts` -> `failed`                    | Inspect `job_events`, fix the root cause, then `/jobs/{id}/retry`.     |
| `cross-device link` from exporter | `work_dir` and `output_dir` on different filesystems     | Same dataset; preflight will catch this on next boot.                  |
| Empty / blank parts in output     | OCR returned no text                                     | Check OCR backend logs; reprocess after fixing.                        |
| AI proposals all rejected         | Validator rejected (e.g. missing keyword evidence)       | Inspect `split_decisions` for `reason_code`; tune `ai.evidence`.       |

## Stopping cleanly

Send `SIGTERM` (Compose does this on `down`). Tini propagates it; the
worker drains the in-flight job, releases its lock, and exits.

## Backups

See [`backups.md`](backups.md).

## TrueNAS deployment

See [`truenas.md`](truenas.md).
