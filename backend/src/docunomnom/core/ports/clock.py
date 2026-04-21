"""Clock port. Allows tests to inject deterministic time."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ClockPort(Protocol):
    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime (UTC)."""
        ...
