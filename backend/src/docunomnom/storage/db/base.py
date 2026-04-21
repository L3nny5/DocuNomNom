"""SQLAlchemy declarative base.

Kept in its own module so Alembic ``env.py`` and the ORM models can both
import it without creating an import cycle.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
