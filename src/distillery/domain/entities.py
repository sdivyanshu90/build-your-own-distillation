"""Domain entities — objects with stable identity and a lifecycle.

Unlike value objects, entities are mutable and identified by an ``id`` rather
than their attributes. :class:`DistillationJob` is the aggregate root: it owns
its progress, evaluation, artifacts and the legal transitions of its lifecycle,
and records :mod:`distillery.domain.events` for the outbox/event-bus pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from distillery.domain.enums import ArtifactType, JobStatus, Role
from distillery.domain.events import (
    DomainEvent,
    JobCompleted,
    JobFailed,
    JobProgressed,
    JobStarted,
)
from distillery.domain.exceptions import InvalidStateTransitionError
from distillery.domain.value_objects import (
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    ResourceUsage,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# Legal job lifecycle transitions. Any transition not listed here is rejected.
_LEGAL_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


@dataclass
class Artifact:
    """A persisted output of a job (model weights, report, dataset, ...)."""

    job_id: str
    type: ArtifactType
    uri: str
    size_bytes: int = 0
    checksum: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class User:
    """An authenticated principal."""

    email: str
    role: Role = Role.VIEWER
    hashed_password: str | None = None
    is_active: bool = True
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)

    def can(self, required: Role) -> bool:
        """Return True if this user's role meets or exceeds ``required``."""
        return self.is_active and self.role.rank >= required.rank


@dataclass
class ApiKey:
    """A hashed API key credential bound to an owner and role."""

    name: str
    prefix: str
    hashed_key: str
    owner_id: str
    role: Role = Role.OPERATOR
    is_active: bool = True
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)
    last_used_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # Some backends (e.g. SQLite) return naive datetimes; treat as UTC.
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return _utcnow() >= expires

    @property
    def is_usable(self) -> bool:
        return self.is_active and not self.is_expired


@dataclass
class DistillationJob:
    """Aggregate root modelling a single distillation run end-to-end."""

    name: str
    config: DistillationConfig
    owner_id: str
    status: JobStatus = JobStatus.PENDING
    progress: JobProgress = field(default_factory=JobProgress)
    evaluation: EvaluationReport | None = None
    resource_usage: ResourceUsage | None = None
    error: str | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    task_id: str | None = None
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    # -- lifecycle ---------------------------------------------------------
    def transition_to(self, new_status: JobStatus) -> None:
        """Validate and apply a lifecycle transition.

        Raises:
            InvalidStateTransitionError: if the transition is not permitted.
        """
        allowed = _LEGAL_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition job from {self.status.value} to {new_status.value}.",
                details={"from": self.status.value, "to": new_status.value},
            )
        self.status = new_status
        self._touch()

    def mark_queued(self, task_id: str | None = None) -> None:
        self.transition_to(JobStatus.QUEUED)
        if task_id is not None:
            self.task_id = task_id

    def mark_running(self) -> None:
        self.transition_to(JobStatus.RUNNING)
        self.started_at = _utcnow()
        self._record(JobStarted(job_id=self.id))

    def update_progress(self, progress: JobProgress) -> None:
        if self.status is not JobStatus.RUNNING:
            raise InvalidStateTransitionError("Progress can only be updated while RUNNING.")
        self.progress = progress
        self._touch()
        self._record(
            JobProgressed(job_id=self.id, percent=progress.percent, message=progress.message)
        )

    def mark_succeeded(
        self,
        evaluation: EvaluationReport,
        resource_usage: ResourceUsage,
        artifacts: list[Artifact] | None = None,
    ) -> None:
        self.transition_to(JobStatus.SUCCEEDED)
        self.evaluation = evaluation
        self.resource_usage = resource_usage
        if artifacts:
            self.artifacts.extend(artifacts)
        self.finished_at = _utcnow()
        self._record(JobCompleted(job_id=self.id, primary_metric=evaluation.primary_metric))

    def mark_failed(self, error: str) -> None:
        self.transition_to(JobStatus.FAILED)
        self.error = error
        self.finished_at = _utcnow()
        self._record(JobFailed(job_id=self.id, error=error))

    def cancel(self) -> None:
        self.transition_to(JobStatus.CANCELLED)
        self.finished_at = _utcnow()

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)
        self._touch()

    # -- events ------------------------------------------------------------
    def pull_events(self) -> list[DomainEvent]:
        """Return and clear the buffered domain events (transactional outbox)."""
        events, self._events = self._events, []
        return events

    # -- internals ---------------------------------------------------------
    def _record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def _touch(self) -> None:
        self.updated_at = _utcnow()
