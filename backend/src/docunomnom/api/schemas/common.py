"""Shared API DTOs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """Simple offset/limit page envelope."""

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class ErrorResponse(BaseModel):
    """Uniform error envelope for non-2xx responses."""

    code: str
    message: str
