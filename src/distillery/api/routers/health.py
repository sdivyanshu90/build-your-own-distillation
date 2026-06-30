"""Liveness, readiness and metrics endpoints (unauthenticated, unversioned)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from sqlalchemy import text
from starlette import status

from distillery.api.schemas.common import HealthResponse, ReadinessResponse
from distillery.config.settings import get_settings
from distillery.infrastructure.db.session import get_session_factory
from distillery.infrastructure.observability.metrics import render_latest
from distillery.version import __version__

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Always returns 200 while the process is alive."""
    return HealthResponse(service=get_settings().service_name, version=__version__)


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
def ready(response: Response) -> ReadinessResponse:
    """Reports readiness, verifying the database is reachable."""
    checks: dict[str, str] = {}
    healthy = True
    try:
        with get_session_factory()() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("Readiness DB check failed: %s", exc)
        checks["database"] = "error"
        healthy = False

    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if healthy else "degraded", checks=checks)


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
def metrics() -> Response:
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)
