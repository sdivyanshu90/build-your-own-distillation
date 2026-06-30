"""Shared API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Readiness probe response with per-dependency checks."""

    status: str = Field(description="'ok' if all critical dependencies are healthy.")
    checks: dict[str, str] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """The standard error envelope returned by every failing endpoint."""

    error: ErrorDetail
