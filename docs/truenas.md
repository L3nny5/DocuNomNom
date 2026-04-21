# TrueNAS deployment notes

DocuNomNom v1 is built for TrueNAS SCALE running the standard Docker /
compose runtime. This document captures the deployment-specific
guardrails.

## Dataset layout (recommended)

Create one ZFS dataset and put every DocuNomNom path inside it:

```
/mnt/tank/docunomnom/
  input/      # operators drop PDFs here (could also be a paperless inbox you mirror in)
  output/     # mounted into paperless-ngx as its consume directory
  work/       # atomic staging (same dataset == same fs as output and archive)
  archive/    # originals after successful export
  data/       # SQLite database + run-time state
  config/     # config.yaml, optional operator overrides
```

If you want `output/` to live inside paperless-ngx's own dataset, put
`work/` and `archive/` on the SAME dataset as `output/`. The exporter
relies on `rename(2)` being atomic between work and output, and the
preflight refuses to start when they straddle two filesystems.

## Why local-only for the SQLite DB

WAL durability and locking semantics rely on POSIX `fsync` and
`fcntl(F_SETLK)`. NFS, CIFS/SMB, FUSE (sshfs/rclone) and 9p do not
provide them reliably, and corruption is very real. The preflight
parses `/proc/mounts` and refuses to boot when the DB lives on one of
those filesystems. Use a local ZFS dataset.

## Permissions

The image runs as a fixed `app` user (UID/GID 1000 by default). Set
`PUID` and `PGID` in compose to match the owner of the dataset on the
TrueNAS side. The entrypoint:

1. Calls `usermod`/`groupmod` to reassign the in-image `app` user.
2. `chown`s every mount to `PUID:PGID` (best effort).
3. Refuses to start when any mount is not writable for the resolved
   UID.

## Compose

Use the two compose files together:

```bash
docker compose \
  -f deploy/docker/compose.yaml \
  -f deploy/docker/compose.truenas.yaml \
  up -d
```

Override paths via env vars, typically in a `.env` file next to the
compose files:

```env
PUID=1000
PGID=1000
INPUT_DIR=/mnt/tank/docunomnom/input
OUTPUT_DIR=/mnt/tank/paperless/consume
WORK_DIR=/mnt/tank/docunomnom/work
ARCHIVE_DIR=/mnt/tank/docunomnom/archive
DATA_DIR=/mnt/tank/docunomnom/data
CONFIG_DIR=/mnt/tank/docunomnom/config
```

## Integrating with paperless-ngx

- Point `OUTPUT_DIR` at paperless's `CONSUME_DIR`.
- Make sure paperless and the DocuNomNom worker run as the same UID/GID
  (or a shared group with permissive ACLs); otherwise paperless will
  not be able to delete the consumed files.
- Atomic rename(2) means paperless never picks up half-written PDFs.
  No additional "stable file" delay is required on the paperless side.

## Single-replica invariant

Compose declares `replicas: 1` for the worker. Do not raise it. The
worker also enforces this at startup via an advisory PID-file lock
under `work_dir`; a second instance refuses to boot.

## Egress

Outbound network calls are off by default. To enable AI via OpenAI or
the external OCR API:

```env
DOCUNOMNOM__NETWORK__ALLOW_EXTERNAL_EGRESS=true
DOCUNOMNOM__NETWORK__ALLOWED_HOSTS=["api.openai.com"]
```

The OpenAI key is read from the env var named in
`ai.openai.api_key_env` (default `OPENAI_API_KEY`); it is never written
into YAML or the database.
