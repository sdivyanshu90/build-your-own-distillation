"""Domain exception hierarchy.

These exceptions are framework-agnostic. The API layer maps them to HTTP status
codes in :mod:`distillery.api.errors`; the CLI maps them to exit codes. Each
carries a stable, machine-readable ``code`` for clients and structured logging.
"""

from __future__ import annotations

from typing import Any


class DistilleryError(Exception):
    """Base class for every expected (non-bug) error in the system."""

    #: Stable, machine-readable error code surfaced to API clients.
    code: str = "internal_error"
    #: Default human-readable message; subclasses/instances may override.
    message: str = "An unexpected error occurred."

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        self.message = message or self.message
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(DistilleryError):
    """A request or configuration failed domain validation."""

    code = "validation_error"
    message = "The provided input is invalid."


class EntityNotFoundError(DistilleryError):
    """A referenced entity does not exist."""

    code = "not_found"
    message = "The requested entity was not found."


class JobNotFoundError(EntityNotFoundError):
    code = "job_not_found"
    message = "The requested distillation job was not found."


class ArtifactNotFoundError(EntityNotFoundError):
    code = "artifact_not_found"
    message = "The requested artifact was not found."


class ConflictError(DistilleryError):
    """The operation conflicts with the current state of a resource."""

    code = "conflict"
    message = "The request conflicts with the current resource state."


class InvalidStateTransitionError(ConflictError):
    """An illegal job lifecycle transition was attempted."""

    code = "invalid_state_transition"
    message = "The requested state transition is not allowed."


class AuthenticationError(DistilleryError):
    code = "unauthenticated"
    message = "Authentication is required or the supplied credentials are invalid."


class AuthorizationError(DistilleryError):
    code = "forbidden"
    message = "You do not have permission to perform this action."


class QuotaExceededError(DistilleryError):
    code = "quota_exceeded"
    message = "A usage quota or rate limit has been exceeded."


class TeacherError(DistilleryError):
    """The teacher (HF model or LLM provider) failed to supply supervision."""

    code = "teacher_error"
    message = "The teacher model failed to produce supervision."


class TrainingError(DistilleryError):
    """The distillation training loop failed."""

    code = "training_error"
    message = "Distillation training failed."
