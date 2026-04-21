"""System clock adapter implementing ``ClockPort``.

Convention: all datetimes inside the application are *naive* UTC. SQLite has
no native timezone type, and mixing naive and aware datetimes around the ORM
boundary leads to silent comparison bugs. Naive UTC is the simplest invariant
that survives both SQLite and PostgreSQL; values crossing the API boundary
get serialized as ISO 8601 with an explicit ``Z`` suffix in the API layer.

Tests that need deterministic time should inject a ``FixedClock`` (also
defined here, so test code does not have to invent its own helper)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


def utc_now() -> datetime:
    """Return the current time as a *naive* UTC datetime."""
    return datetime.utcnow()


class SystemClock:
    """Default ``ClockPort`` implementation. Returns naive UTC datetimes."""

    def now(self) -> datetime:
        return utc_now()


@dataclass(slots=True)
class FixedClock:
    """Test double that returns a controllable time (naive UTC by convention)."""

    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float = 0.0) -> None:
        self.current = self.current + timedelta(seconds=seconds)
