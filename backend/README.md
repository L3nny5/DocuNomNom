# DocuNomNom Backend

Python backend (FastAPI api + worker process sharing the same Python
package). **Phase 1 foundations are complete**: domain entities and ports,
state machine, SQLAlchemy schema, Alembic baseline migration, SQLite
bootstrap with the v1 PRAGMAs, DB-backed job queue with lease/heartbeat/
crash-recovery, file stability watcher, and layered configuration.

## Layout

```
src/docunomnom/
  api/         FastAPI app, routers, dependencies (Phase 0: /health only)
  core/        Domain layer (models, ports, run_key, state machine)
  adapters/    Adapters that implement core ports (clock today; OCR/AI later)
  storage/     SQLAlchemy models, repositories, migrations, file helpers
  worker/      Worker process: stability watcher and DB-queue job loop
  config/      Layered settings (defaults.yaml + env vars)
  i18n/        Backend-side reason codes / messages (placeholder)
tests/
  unit/        State machine, run_key, safe_path, settings
  adapter/     Repositories, queue, engine PRAGMAs, Alembic baseline
  api/         /health smoke
  worker/      Watcher and JobLoop
```

## Tooling

- `ruff check .` / `ruff format .` — linting and formatting
- `mypy` — strict static typing
- `lint-imports` — enforces hexagonal boundaries (see `.importlinter`)
- `pytest` — unit + adapter + worker tests
- `alembic upgrade head` — apply the v1 baseline migration
