"""FastAPI application entry point.

Phase 6 wires the operator-facing surface: jobs, history, config,
keywords, and the minimal review workflow. AI processing is integrated
in the worker pipeline (Phase 5); this module exposes only the API
surface — there is no AI endpoint by design.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from ..runtime import LogEvent, configure_logging
from . import __api_version__
from .frontend import mount_frontend
from .routers import config as config_router
from .routers import health, history, jobs, keywords, review

logger = logging.getLogger("docunomnom.api")


def create_app() -> FastAPI:
    """Construct the FastAPI app. Kept as a factory to ease testing."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "%s version=%s pipeline_version=%s",
        LogEvent.API_STARTING,
        __api_version__,
        settings.runtime.pipeline_version,
    )

    app = FastAPI(
        title="DocuNomNom",
        version=__api_version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )

    # CORS is wide-open in v1 because the UI ships from the same origin
    # in production. Local dev runs Vite on :5173 against the API on
    # :8000 and needs the cross-origin allowance.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(jobs.router, prefix=api_prefix)
    app.include_router(history.router, prefix=api_prefix)
    app.include_router(config_router.router, prefix=api_prefix)
    app.include_router(keywords.router, prefix=api_prefix)
    app.include_router(review.router, prefix=api_prefix)

    # Must come AFTER include_router so the SPA catch-all never shadows
    # an API route. A missing bundle simply leaves the app API-only —
    # useful in tests and for operators who front the UI with a
    # separate CDN.
    mount_frontend(app, api_prefix=api_prefix)

    return app


app = create_app()
