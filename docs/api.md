# API

All routes live under `/api/v1`. The OpenAPI schema is served at
`/api/v1/openapi.json` and an interactive UI at `/api/v1/docs`.

There is no AI endpoint by design: AI processing is integrated into the
worker pipeline behind the Evidence Validator and never exposed to the
operator UI as a separate surface.

## Routes

| Method | Path                                  | Purpose                                    |
| ------ | ------------------------------------- | ------------------------------------------ |
| GET    | `/health`                             | Liveness probe (returns `{"status":"ok"}`). |
| GET    | `/jobs`                               | List jobs with pagination + status filter. |
| GET    | `/jobs/{job_id}`                      | Job detail with events.                    |
| POST   | `/jobs/rescan`                        | Run one watcher pass synchronously.        |
| POST   | `/jobs/{job_id}/retry`                | Re-queue a failed job.                     |
| POST   | `/jobs/{job_id}/reprocess`            | Force a fresh analysis (new `run_key`).    |
| GET    | `/history`                            | List historical exported parts.            |
| GET    | `/history/{part_id}`                  | Single part history entry.                 |
| POST   | `/history/{part_id}/reopen`           | Open a new review item for an exported part. |
| GET    | `/config`                             | Read live config snapshot.                 |
| PUT    | `/config`                             | Replace mutable config fields.             |
| GET    | `/config/keywords`                    | List keywords.                             |
| POST   | `/config/keywords`                    | Add a keyword.                             |
| PUT    | `/config/keywords/{id}`               | Update a keyword.                          |
| DELETE | `/config/keywords/{id}`               | Delete a keyword.                          |
| GET    | `/review`                             | List open review items.                    |
| GET    | `/review/{item_id}`                   | Review item detail (proposals, markers).   |
| GET    | `/review/{item_id}/pdf`               | Stream the PDF for the review viewer.      |
| PUT    | `/review/{item_id}/markers`           | Replace the marker set atomically.         |
| POST   | `/review/{item_id}/finalize`          | Apply the reviewed split decisions.        |

## Notes

- All write endpoints validate the request body with Pydantic v2 DTOs;
  ORM models are never returned directly.
- The PDF endpoint streams from `work_dir` / `output_dir` through
  `safe_path` so traversal escapes are rejected.
- Pagination is `limit + offset` with a small max-page cap.
- Errors use FastAPI's standard error envelope; codes are `400` for
  validation, `404` for missing entities, `409` for state conflicts
  (e.g. finalizing a review item that is already done), `422` for
  schema violations.
