"""Job queue port.

The queue lives in the database (see plan: SQLite-as-queue, single-worker
invariant). The worker leases jobs through this port and sends heartbeats to
extend the lease while it works.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from ..models.entities import Job


class JobQueuePort(Protocol):
    def lease_one(
        self,
        *,
        lease_ttl: timedelta,
        max_attempts: int,
    ) -> Job | None:
        """Atomically lease the next available job.

        Returns ``None`` when no job is available. A job is available when it
        is ``pending`` or its ``processing`` lease has expired. When a job is
        leased, its ``attempt`` is incremented; if the result would exceed
        ``max_attempts`` the job is moved to ``failed`` instead and ``None``
        is returned for that attempt.
        """
        ...

    def heartbeat(
        self,
        job_id: int,
        *,
        lease_ttl: timedelta,
    ) -> bool:
        """Extend the lease for a still-running job. Returns False when the
        job is no longer leased to us (e.g. lease already expired)."""
        ...
