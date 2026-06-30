"""FastAPI application factory.

``create_app`` is referenced by Uvicorn/Gunicorn via the ``--factory`` flag
(``distillery.api.app:create_app``). It configures logging, the middleware
stack, exception handlers, versioned routers and a customised OpenAPI document.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from distillery import bootstrap
from distillery.api.errors import install_exception_handlers
from distillery.api.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from distillery.api.routers import auth, health, jobs
from distillery.config.settings import Environment, Settings, get_settings
from distillery.infrastructure.db.seed import ensure_schema, seed_bootstrap
from distillery.infrastructure.db.session import create_db_engine
from distillery.infrastructure.observability.logging import configure_logging

logger = logging.getLogger(__name__)

_DESCRIPTION = """\
**Distillery** distils large teacher transformer models into small, fast student
models via response-based KD, feature-based KD and LLM-teacher data distillation.

Authenticate with an **API key** (`X-API-Key` header) or a **bearer JWT**
(`Authorization: Bearer <token>`). Create a job, poll its status, then download
the resulting student model and evaluation report from its artifacts.
"""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger.info("Starting %s (env=%s)", settings.service_name, settings.env.value)
    try:
        if settings.env is Environment.DEVELOPMENT:
            ensure_schema(create_db_engine(settings.database))
        seed_bootstrap(bootstrap.get_uow_factory(), settings.security)
    except Exception as exc:
        logger.warning("Startup seeding skipped: %s", exc)
    yield
    logger.info("Shutting down %s", settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Distillery API",
        version=_version(),
        description=_DESCRIPTION,
        root_path=settings.api.root_path,
        docs_url="/docs" if settings.api.docs_enabled else None,
        redoc_url="/redoc" if settings.api.docs_enabled else None,
        openapi_url="/openapi.json" if settings.api.docs_enabled else None,
        lifespan=_lifespan,
    )

    # Middleware: added inner→outer. Final outer→inner order is:
    # CORS → SecurityHeaders → RequestContext → BodySizeLimit → RateLimit → app.
    app.add_middleware(
        RateLimitMiddleware,
        limiter=bootstrap.build_rate_limiter(),
        header_name=settings.security.api_key_header,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        )

    install_exception_handlers(app)

    app.include_router(health.router)
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth.router)
    api_v1.include_router(jobs.router)
    app.include_router(api_v1)

    _customise_openapi(app)
    return app


def _version() -> str:
    from distillery.version import __version__

    return __version__


def _customise_openapi(app: FastAPI) -> None:
    """Attach contact/license metadata and stable server entries to the schema."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema["info"]["contact"] = {"name": "Distillery", "email": "info@uniiq.ai"}
        schema["info"]["license"] = {"name": "Apache-2.0"}
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
