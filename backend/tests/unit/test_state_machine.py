"""Tests for the job state machine."""

from __future__ import annotations

import pytest

from docunomnom.core.models import JobStatus
from docunomnom.core.usecases.transition_job import (
    ALLOWED_TRANSITIONS,
    IllegalJobTransitionError,
    ensure_transition_allowed,
    is_transition_allowed,
    transition_label,
)

EXPECTED_TRANSITIONS = {
    (JobStatus.PENDING, JobStatus.PROCESSING): "worker_pickup",
    (JobStatus.PROCESSING, JobStatus.REVIEW_REQUIRED): "uncertain_parts",
    (JobStatus.PROCESSING, JobStatus.COMPLETED): "all_safe_parts_exported",
    (JobStatus.PROCESSING, JobStatus.FAILED): "error",
    (JobStatus.REVIEW_REQUIRED, JobStatus.PROCESSING): "user_finalize",
    (JobStatus.REVIEW_REQUIRED, JobStatus.COMPLETED): "user_finalize_all",
    (JobStatus.FAILED, JobStatus.PENDING): "retry",
    (JobStatus.COMPLETED, JobStatus.REVIEW_REQUIRED): "history_reopen",
}


def test_transition_table_matches_plan() -> None:
    assert dict(ALLOWED_TRANSITIONS) == EXPECTED_TRANSITIONS


_PARAMS = [(s, d, lab) for (s, d), lab in EXPECTED_TRANSITIONS.items()]


@pytest.mark.parametrize(("src", "dst", "label"), _PARAMS)
def test_allowed_transitions(src: JobStatus, dst: JobStatus, label: str) -> None:
    assert is_transition_allowed(src, dst) is True
    assert transition_label(src, dst) == label
    ensure_transition_allowed(src, dst)


def _all_pairs() -> list[tuple[JobStatus, JobStatus]]:
    return [(a, b) for a in JobStatus for b in JobStatus]


@pytest.mark.parametrize(
    ("src", "dst"),
    [pair for pair in _all_pairs() if pair not in EXPECTED_TRANSITIONS],
)
def test_disallowed_transitions_raise(src: JobStatus, dst: JobStatus) -> None:
    assert is_transition_allowed(src, dst) is False
    with pytest.raises(IllegalJobTransitionError) as exc_info:
        ensure_transition_allowed(src, dst)
    assert exc_info.value.current is src
    assert exc_info.value.target is dst


def test_self_transitions_disallowed() -> None:
    for s in JobStatus:
        assert is_transition_allowed(s, s) is False


def test_completed_can_only_reopen_to_review() -> None:
    assert is_transition_allowed(JobStatus.COMPLETED, JobStatus.REVIEW_REQUIRED)
    assert not is_transition_allowed(JobStatus.COMPLETED, JobStatus.PENDING)
    assert not is_transition_allowed(JobStatus.COMPLETED, JobStatus.PROCESSING)
    assert not is_transition_allowed(JobStatus.COMPLETED, JobStatus.FAILED)


def test_failed_can_only_retry() -> None:
    assert is_transition_allowed(JobStatus.FAILED, JobStatus.PENDING)
    assert not is_transition_allowed(JobStatus.FAILED, JobStatus.PROCESSING)
    assert not is_transition_allowed(JobStatus.FAILED, JobStatus.COMPLETED)
    assert not is_transition_allowed(JobStatus.FAILED, JobStatus.REVIEW_REQUIRED)
