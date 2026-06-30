"""Ports — the abstract boundaries the application depends on.

Following the Dependency Inversion Principle, the application layer is written
against these interfaces only. Concrete adapters live in
:mod:`distillery.infrastructure` and :mod:`distillery.core`. Ports are declared
as :class:`typing.Protocol` so adapters need not inherit from them — they only
need to match structurally, which keeps test doubles trivial.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User
from distillery.domain.enums import ArtifactType, JobStatus
from distillery.domain.events import DomainEvent
from distillery.domain.value_objects import (
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    ResourceUsage,
)

# A callback invoked by the engine to report incremental progress.
ProgressCallback = Callable[[JobProgress], None]


@dataclass(frozen=True)
class EngineArtifact:
    """An artifact produced on local disk by the engine, awaiting storage."""

    type: ArtifactType
    local_path: Path
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineResult:
    """The complete output of an engine run."""

    evaluation: EvaluationReport
    resource_usage: ResourceUsage
    artifacts: list[EngineArtifact] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------
@runtime_checkable
class JobRepository(Protocol):
    """Persistence boundary for :class:`DistillationJob` aggregates."""

    def add(self, job: DistillationJob) -> DistillationJob: ...

    def get(self, job_id: str) -> DistillationJob | None: ...

    def update(self, job: DistillationJob) -> DistillationJob: ...

    def delete(self, job_id: str) -> None: ...

    def list(
        self,
        *,
        owner_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[DistillationJob]: ...

    def count(self, *, owner_id: str | None = None, status: JobStatus | None = None) -> int: ...


@runtime_checkable
class UserRepository(Protocol):
    def add(self, user: User) -> User: ...

    def get(self, user_id: str) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[User]: ...


@runtime_checkable
class ApiKeyRepository(Protocol):
    def add(self, api_key: ApiKey) -> ApiKey: ...

    def get_by_prefix(self, prefix: str) -> ApiKey | None: ...

    def update(self, api_key: ApiKey) -> ApiKey: ...

    def list_for_owner(self, owner_id: str) -> Sequence[ApiKey]: ...


@runtime_checkable
class ArtifactRepository(Protocol):
    def add(self, artifact: Artifact) -> Artifact: ...

    def get(self, artifact_id: str) -> Artifact | None: ...

    def list_for_job(self, job_id: str) -> Sequence[Artifact]: ...


# ---------------------------------------------------------------------------
# Unit of Work
# ---------------------------------------------------------------------------
@runtime_checkable
class UnitOfWork(Protocol):
    """Transactional boundary aggregating repositories.

    Used as a context manager; exiting without an explicit :meth:`commit`
    rolls back. This gives application services a single atomic transaction.
    """

    jobs: JobRepository
    users: UserRepository
    api_keys: ApiKeyRepository
    artifacts: ArtifactRepository

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, *exc: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


# ---------------------------------------------------------------------------
# Storage / queue / events / engine
# ---------------------------------------------------------------------------
@runtime_checkable
class ArtifactStorage(Protocol):
    """Content-addressable artifact storage (local FS or object store)."""

    def save_file(self, local_path: Path, key: str) -> str:
        """Persist a single file under ``key``; return its storage URI."""
        ...

    def save_directory(self, local_dir: Path, key_prefix: str) -> str:
        """Persist a directory tree; return the URI of its root."""
        ...

    def open_stream(self, key: str) -> bytes:
        """Return the raw bytes stored at ``key``."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def uri_for(self, key: str) -> str: ...


@runtime_checkable
class TaskQueue(Protocol):
    """Asynchronous execution boundary (Celery in production)."""

    def enqueue_distillation(self, job_id: str) -> str:
        """Schedule a job for background execution; return the task id."""
        ...

    def cancel(self, task_id: str) -> None: ...


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes domain events to interested subscribers."""

    def publish(self, events: Sequence[DomainEvent]) -> None: ...


@runtime_checkable
class DistillationEngine(Protocol):
    """The core distillation execution boundary."""

    def run(
        self,
        config: DistillationConfig,
        *,
        work_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> EngineResult: ...
