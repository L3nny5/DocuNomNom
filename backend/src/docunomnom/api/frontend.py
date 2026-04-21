"""Static-file + SPA serving for the built Vite/React bundle.

The Docker image copies the production frontend build into
``/app/frontend-dist`` (see ``deploy/docker/Dockerfile``). This module
wires that bundle into the FastAPI app without touching the ``/api/v1``
surface:

* ``/assets/*`` is served from ``<dist>/assets`` via Starlette's
  ``StaticFiles`` — hashed Vite chunks with long-lived ``Cache-Control``
  semantics out of the box.
* ``/`` returns ``<dist>/index.html``.
* Any non-API path that does not resolve to a real file under ``<dist>``
  falls back to ``index.html`` so client-side routes (``/jobs``,
  ``/history``, ``/review/<id>``, ...) work on a hard refresh.
* Paths under the API prefix never fall back: they must return whatever
  the API router decided (200/404 JSON), never HTML. This avoids the
  common SPA-in-FastAPI trap where ``/api/v1/nonexistent`` silently
  returns ``index.html``.

The resolver is path-traversal-safe: ``../`` segments that would escape
``<dist>`` are rejected.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("docunomnom.api.frontend")

# Env override lets operators relocate the bundle without rebuilding the
# image (e.g. bind-mount a patched UI on top of the default). The
# default matches what the production Dockerfile writes.
FRONTEND_DIST_ENV = "DOCUNOMNOM_FRONTEND_DIST"
DEFAULT_FRONTEND_DIST = Path("/app/frontend-dist")


def resolve_frontend_dist() -> Path | None:
    """Return the frontend bundle directory, or ``None`` if it is not
    usable.

    A directory is considered usable when it exists and contains an
    ``index.html`` — partial or missing bundles are rejected early so
    the API never serves half of an SPA.
    """
    raw = os.environ.get(FRONTEND_DIST_ENV)
    candidate = Path(raw) if raw else DEFAULT_FRONTEND_DIST
    if not candidate.is_dir():
        return None
    if not (candidate / "index.html").is_file():
        return None
    return candidate.resolve()


def mount_frontend(app: FastAPI, *, api_prefix: str = "/api/v1") -> bool:
    """Install static / SPA serving on ``app`` if a bundle is available.

    Returns ``True`` when the bundle was mounted, ``False`` otherwise.
    Must be called AFTER all API routers have been included on the app,
    so that the SPA catch-all never shadows an API route.
    """
    dist_dir = resolve_frontend_dist()
    if dist_dir is None:
        logger.info(
            "frontend.bundle.absent env=%s default=%s; skipping SPA mount",
            FRONTEND_DIST_ENV,
            DEFAULT_FRONTEND_DIST,
        )
        return False

    index_path = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    api_prefix_stripped = api_prefix.strip("/")

    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_dir),
            name="frontend-assets",
        )

    @app.get("/", include_in_schema=False)
    async def _serve_index() -> FileResponse:
        return FileResponse(index_path, media_type="text/html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_spa(full_path: str) -> Response:
        # Do not hijack the API surface. A request that reaches the
        # catch-all under the API prefix means the API router already
        # declined it; the correct response is a JSON 404 from FastAPI,
        # not HTML.
        normalized = full_path.lstrip("/")
        if normalized == api_prefix_stripped or normalized.startswith(api_prefix_stripped + "/"):
            raise HTTPException(status_code=404)

        # Resolve against the bundle and refuse anything that escapes it
        # via ``..`` segments.
        candidate = (dist_dir / normalized).resolve()
        try:
            candidate.relative_to(dist_dir)
        except ValueError:
            raise HTTPException(status_code=404) from None

        if candidate.is_file():
            return FileResponse(candidate)
        # SPA fallback: any unknown non-API path renders the shell and
        # lets the client router take over.
        return FileResponse(index_path, media_type="text/html")

    logger.info("frontend.mounted dist=%s assets=%s", dist_dir, assets_dir.is_dir())
    return True
