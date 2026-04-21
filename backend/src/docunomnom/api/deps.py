"""Shared FastAPI dependencies.

Wires the database engine, the SQLAlchemy session factory, and the loaded
``Settings`` into the FastAPI app so routers can declare their needs via
``Depends``. The placeholder auth slot lives here too so future phases
can swap in a real backend without touching routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..adapters.clock import SystemClock
from ..config import Settings, get_settings
from ..core.ports.clock import ClockPort
from ..storage.db import (
    create_engine,
    make_session_factory,
)


@dataclass(frozen=True)
class Principal:
    """A subject acting against the API."""

    subject: str
    capabilities: frozenset[str]


def get_principal() -> Principal:
    """Return the current principal.

    In v1 this is always an anonymous principal with full capabilities.
    Future phases swap this with a real auth backend (API key, OIDC).
    """
    return Principal(subject="anonymous", capabilities=frozenset({"*"}))


def get_app_settings() -> Settings:
    """Return the cached application settings."""
    return get_settings()


def get_clock() -> ClockPort:
    return SystemClock()


def _build_state_engine(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(settings.storage.database_url)
    factory = make_session_factory(engine)
    return engine, factory


def get_engine(request: Request) -> Engine:
    """Lazy per-app engine, attached to ``app.state`` on first use."""
    state = request.app.state
    engine: Engine | None = getattr(state, "engine", None)
    if engine is None:
        settings = get_app_settings()
        engine, factory = _build_state_engine(settings)
        state.engine = engine
        state.session_factory = factory
    return engine


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """Lazy per-app session factory; pairs with ``get_engine``."""
    state = request.app.state
    factory: sessionmaker[Session] | None = getattr(state, "session_factory", None)
    if factory is None:
        get_engine(request)
        factory = state.session_factory
    assert factory is not None
    return factory


def get_session(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Iterator[Session]:
    """Open a short-lived transactional session per request.

    Commits on success, rolls back on exception, always closes. Routers
    must keep heavy CPU/IO work outside this scope (plan §3) — but for
    Phase 3 the API does no such work, only DB reads and small writes.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
