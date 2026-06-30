"""Domain layer — pure business model with no framework dependencies.

Nothing in this package may import infrastructure, web, or ML libraries
(torch, sqlalchemy, fastapi, ...). It defines *what* the system is, expressed
as entities, value objects, events, errors and ports (abstract interfaces).
The outer layers depend inward on this package, never the reverse.
"""

from __future__ import annotations

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User
from distillery.domain.enums import (
    ArtifactType,
    DatasetFormat,
    DistillationStrategy,
    JobStatus,
    ModelTask,
    Role,
    TeacherType,
)
from distillery.domain.events import (
    DomainEvent,
    JobCompleted,
    JobFailed,
    JobProgressed,
    JobStarted,
)
from distillery.domain.exceptions import (
    ArtifactNotFoundError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DistilleryError,
    EntityNotFoundError,
    InvalidStateTransitionError,
    JobNotFoundError,
    QuotaExceededError,
    TeacherError,
    TrainingError,
    ValidationError,
)
from distillery.domain.value_objects import (
    CompressionStats,
    DatasetSpec,
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    KDHyperParams,
    LLMTeacherConfig,
    ModelSpec,
    ResourceUsage,
    TrainingConfig,
)

__all__ = [
    # entities
    "ApiKey",
    "Artifact",
    "DistillationJob",
    "User",
    # enums
    "ArtifactType",
    "DatasetFormat",
    "DistillationStrategy",
    "JobStatus",
    "ModelTask",
    "Role",
    "TeacherType",
    # events
    "DomainEvent",
    "JobCompleted",
    "JobFailed",
    "JobProgressed",
    "JobStarted",
    # exceptions
    "ArtifactNotFoundError",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "DistilleryError",
    "EntityNotFoundError",
    "InvalidStateTransitionError",
    "JobNotFoundError",
    "QuotaExceededError",
    "TeacherError",
    "TrainingError",
    "ValidationError",
    # value objects
    "CompressionStats",
    "DatasetSpec",
    "DistillationConfig",
    "EvaluationReport",
    "JobProgress",
    "KDHyperParams",
    "LLMTeacherConfig",
    "ModelSpec",
    "ResourceUsage",
    "TrainingConfig",
]
