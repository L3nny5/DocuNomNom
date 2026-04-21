"""Liveness probe.

This is the only real route in Phase 0. It must remain dependency-free so it
can answer even when downstream services (DB, OCR, AI) are not available.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
