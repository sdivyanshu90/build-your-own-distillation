"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from distillery.api.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    LoginRequest,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
)
from distillery.api.schemas.common import HealthResponse, ReadinessResponse
from distillery.api.schemas.jobs import (
    ArtifactResponse,
    EvaluationResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)

__all__ = [
    "ApiKeyCreateRequest",
    "ApiKeyCreateResponse",
    "ApiKeyResponse",
    "ArtifactResponse",
    "EvaluationResponse",
    "HealthResponse",
    "JobCreateRequest",
    "JobListResponse",
    "JobResponse",
    "LoginRequest",
    "ReadinessResponse",
    "TokenResponse",
    "UserCreateRequest",
    "UserResponse",
]
