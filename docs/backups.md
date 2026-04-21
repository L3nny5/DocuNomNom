# Backups & recovery

DocuNomNom keeps three classes of state on disk. Back them up
together and your recovery will be straightforward.

## What to back up

| What                    | Path                                | Notes                                              |
| ----------------------- | ----------------------------------- | -------------------------------------------------- |
| SQLite database         | `${DATA_DIR}/docunomnom.sqlite3`    | Includes WAL + SHM sidecar files; back up all three or use the snapshot procedure below. |
| Configuration           | `${CONFIG_DIR}/config.yaml`         | Plus any operator-edited keyword list inside the DB. |
| Archived originals      | `${ARCHIVE_DIR}/`                   | The PDFs that were already exported to paperless.  |
| Output (transient)      | `${OUTPUT_DIR}/`                    | Usually paperless-ngx's consume dir; paperless will already be backing up the canonical document store. Backing this up is optional. |
| `work_dir`              | `${WORK_DIR}/`                      | Transient; do not back up. Safe to wipe between runs (clears any half-finished OCR artifacts). |

## SQLite snapshot procedure

Cold copy is simplest and safe because the worker is single-process:

```
docker compose stop worker
cp ${DATA_DIR}/docunomnom.sqlite3 /backups/docunomnom-$(date +%F).sqlite3
docker compose start worker
```

Hot copy with WAL is also safe if you use the SQLite CLI:

```
sqlite3 ${DATA_DIR}/docunomnom.sqlite3 ".backup '/backups/docunomnom-$(date +%F).sqlite3'"
```

`.backup` is online; the worker can keep running.

## Restoring

1. Stop both `api` and `worker` services.
2. Replace `${DATA_DIR}/docunomnom.sqlite3` with the backup. Remove
   any leftover `*.sqlite3-wal` and `*.sqlite3-shm` sidecar files.
3. Start `worker` first (it runs migrations), then `api`.

## Disaster recovery: lost DB, intact archive

The archive holds every PDF that was ever successfully exported.
Re-feeding the archive into the input dir is a safe rebuild path:
the watcher's `run_key` derivation (file_sha256 + config_snapshot.hash
+ pipeline_version) will deduplicate already-exported parts as long as
`pipeline_version` matches.

If `pipeline_version` differs (e.g. a code upgrade), every file will be
reprocessed; no data is lost but paperless will see the same documents
again — paperless's own dedupe (file SHA) handles that.

## What is NOT backed up

- The advisory `${WORK_DIR}/.docunomnom_worker.lock` file. Re-created
  on each worker boot.
- Any partial OCR artifact under `${WORK_DIR}/ocr-artifacts/`.
  Worker reprocesses on next attempt.
- Logs (rely on the container runtime / Docker log driver).
