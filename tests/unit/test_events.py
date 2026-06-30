"""Unit tests for domain events and publishers."""

from __future__ import annotations

import pytest

from distillery.domain.events import JobCompleted, JobFailed, JobProgressed, JobStarted
from distillery.infrastructure.events import (
    CollectingEventPublisher,
    LoggingEventPublisher,
    NullEventPublisher,
)

pytestmark = pytest.mark.unit


def test_event_names_and_metadata() -> None:
    event = JobStarted(job_id="j1")
    assert event.name == "JobStarted"
    assert event.event_id
    assert event.occurred_at is not None


def test_collecting_publisher() -> None:
    pub = CollectingEventPublisher()
    events = [
        JobStarted(job_id="j"),
        JobProgressed(job_id="j", percent=50.0),
        JobCompleted(job_id="j", primary_metric=0.9),
    ]
    pub.publish(events)
    assert len(pub.events) == 3
    assert isinstance(pub.events[-1], JobCompleted)


def test_logging_publisher_does_not_raise() -> None:
    LoggingEventPublisher().publish([JobFailed(job_id="j", error="x")])


def test_null_publisher_noop() -> None:
    assert NullEventPublisher().publish([JobStarted(job_id="j")]) is None
