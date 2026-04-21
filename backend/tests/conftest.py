"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docunomnom.adapters.clock import FixedClock
from docunomnom.api.deps import (
    get_engine,
    get_session_factory,
)
from docunomnom.api.main import create_app
from docunomnom.storage.db import (
    create_all_for_tests,
    create_engine,
    make_session_factory,
)


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(current=datetime(2026, 4, 19, 12, 0, 0))


@pytest.fixture
def engine() -> Iterator[Engine]:
    """In-memory SQLite engine with the v1 PRAGMAs and full schema."""
    eng = create_engine("sqlite://")
    create_all_for_tests(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    s = session_factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def api_client(
    engine: Engine,
    session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    """FastAPI TestClient bound to the in-memory test engine."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
