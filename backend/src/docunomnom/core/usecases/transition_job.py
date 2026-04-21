"""Job state machine.

This is the single source of truth for which job status transitions are
allowed. Repositories and the queue must call ``ensure_transition_allowed``
before persisting a status change.

The transition table mirrors plan §8:

  pending          -> processing       : worker_pickup
  processing       -> review_required  : uncertain_parts
  processing       -> completed        : all_safe_parts_exported
  processing       -> failed           : error
  review_required  -> processing       : user_finalize
  review_required  -> completed        : user_finalize_all
  failed           -> pending          : retry
  completed        -> review_required  : history_reopen
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models.types import JobStatus

ALLOWED_TRANSITIONS: Mapping[tuple[JobStatus, JobStatus], str] = {
    (JobStatus.PENDING, JobStatus.PROCESSING): "worker_pickup",
    (JobStatus.PROCESSING, JobStatus.REVIEW_REQUIRED): "uncertain_parts",
    (JobStatus.PROCESSING, JobStatus.COMPLETED): "all_safe_parts_exported",
    (JobStatus.PROCESSING, JobStatus.FAILED): "error",
    (JobStatus.REVIEW_REQUIRED, JobStatus.PROCESSING): "user_finalize",
    (JobStatus.REVIEW_REQUIRED, JobStatus.COMPLETED): "user_finalize_all",
    (JobStatus.FAILED, JobStatus.PENDING): "retry",
    (JobStatus.COMPLETED, JobStatus.REVIEW_REQUIRED): "history_reopen",
}


class IllegalJobTransitionError(ValueError):
    """Raised when a status transition is not in the whitelist."""

    def __init__(self, *, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"Illegal job transition: {current.value} -> {target.value}")
        self.current = current
        self.target = target


def is_transition_allowed(current: JobStatus, target: JobStatus) -> bool:
    """Return True if ``current -> target`` is in the whitelist."""
    return (current, target) in ALLOWED_TRANSITIONS


def transition_label(current: JobStatus, target: JobStatus) -> str:
    """Return the canonical label for an allowed transition."""
    try:
        return ALLOWED_TRANSITIONS[(current, target)]
    except KeyError as exc:
        raise IllegalJobTransitionError(current=current, target=target) from exc


def ensure_transition_allowed(current: JobStatus, target: JobStatus) -> None:
    """Raise ``IllegalJobTransitionError`` if the transition is not allowed."""
    if not is_transition_allowed(current, target):
        raise IllegalJobTransitionError(current=current, target=target)
