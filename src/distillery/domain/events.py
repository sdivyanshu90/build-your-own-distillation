"""Domain events emitted by aggregates.

Events are immutable facts about something that has happened. They are buffered
on the aggregate (see :meth:`DistillationJob.pull_events`) and later dispatched
by the application layer to subscribers (webhooks, metrics, audit log) following
the transactional-outbox pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()), kw_only=True)
    occurred_at: datetime = field(default_factory=_utcnow, kw_only=True)

    @property
    def name(self) -> str:
        return type(self).__name__


@dataclass(frozen=True)
class JobStarted(DomainEvent):
    job_id: str = ""


@dataclass(frozen=True)
class JobProgressed(DomainEvent):
    job_id: str = ""
    percent: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class JobCompleted(DomainEvent):
    job_id: str = ""
    primary_metric: float = 0.0


@dataclass(frozen=True)
class JobFailed(DomainEvent):
    job_id: str = ""
    error: str = ""
