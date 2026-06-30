"""Composition root — assembles concrete adapters into application services.

This is the *only* place where the layers are wired together. Both the API
(``distillery.api.deps``) and the worker (``distillery.infrastructure.queue.tasks``)
obtain fully-constructed services from here, so dependency wiring lives in one
auditable module. Heavy imports (torch via the engine) are deferred to the
functions that need them, keeping API/worker start-up fast.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import cast

from distillery.application.services.auth_service import AuthService
from distillery.application.services.job_service import JobService
from distillery.application.services.pipeline_service import PipelineService
from distillery.config.settings import Settings, get_settings
from distillery.domain.ports import (
    ArtifactStorage,
    DistillationEngine,
    EventPublisher,
    TaskQueue,
    UnitOfWork,
)
from distillery.infrastructure.db.repositories import SqlAlchemyUnitOfWork
from distillery.infrastructure.db.session import get_session_factory
from distillery.infrastructure.events import LoggingEventPublisher
from distillery.infrastructure.queue.adapters import CeleryTaskQueue, InlineTaskQueue
from distillery.infrastructure.security.authentication import Authenticator
from distillery.infrastructure.security.rate_limit import InMemoryRateLimiter, RateLimiter
from distillery.infrastructure.storage import build_storage

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_uow_factory() -> Callable[[], UnitOfWork]:
    """Return a factory that yields a fresh Unit of Work per call."""
    session_factory = get_session_factory()
    return cast("Callable[[], UnitOfWork]", lambda: SqlAlchemyUnitOfWork(session_factory))


@lru_cache(maxsize=1)
def get_storage() -> ArtifactStorage:
    return build_storage(get_settings().storage)


@lru_cache(maxsize=1)
def get_event_publisher() -> EventPublisher:
    return LoggingEventPublisher()


@lru_cache(maxsize=1)
def get_engine() -> DistillationEngine:
    from distillery.core.engine import DefaultDistillationEngine

    return DefaultDistillationEngine()


@lru_cache(maxsize=1)
def build_pipeline_service() -> PipelineService:
    return PipelineService(
        get_uow_factory(),
        get_storage(),
        get_engine(),
        get_event_publisher(),
    )


@lru_cache(maxsize=1)
def build_task_queue() -> TaskQueue:
    settings = get_settings()
    if settings.queue.eager:
        logger.warning("Queue running in EAGER mode — jobs execute synchronously")
        return InlineTaskQueue(build_pipeline_service().run_job)
    return CeleryTaskQueue()


@lru_cache(maxsize=1)
def build_job_service() -> JobService:
    return JobService(
        get_uow_factory(),
        build_task_queue(),
        get_event_publisher(),
        storage=get_storage(),
    )


@lru_cache(maxsize=1)
def build_auth_service() -> AuthService:
    return AuthService(get_uow_factory(), get_settings().security)


@lru_cache(maxsize=1)
def build_authenticator() -> Authenticator:
    return Authenticator(get_uow_factory(), get_settings().security)


@lru_cache(maxsize=1)
def build_rate_limiter() -> RateLimiter:
    settings = get_settings()
    limit = settings.security.rate_limit_per_minute
    broker = settings.queue.broker_url
    if broker.startswith("redis"):
        try:
            import redis

            from distillery.infrastructure.security.rate_limit import RedisRateLimiter

            # Verify connectivity NOW and fall back to in-memory if Redis is
            # unreachable. Otherwise a client that cannot connect would only fail
            # later, per-request, inside the rate-limit middleware (turning every
            # request into a 500 — exactly what broke CI where Redis is absent).
            client = redis.Redis.from_url(broker, socket_connect_timeout=1)
            client.ping()
            return RedisRateLimiter(client, limit)  # pragma: no cover - needs live Redis
        except Exception as exc:
            logger.warning("Redis rate limiter unavailable (%s); using in-memory limiter", exc)
    return InMemoryRateLimiter(limit)


def reset_caches() -> None:
    """Clear all cached singletons (used by tests after changing settings)."""
    for fn in (
        get_uow_factory,
        get_storage,
        get_event_publisher,
        get_engine,
        build_pipeline_service,
        build_task_queue,
        build_job_service,
        build_auth_service,
        build_authenticator,
        build_rate_limiter,
    ):
        fn.cache_clear()  # type: ignore[attr-defined]


def settings() -> Settings:
    return get_settings()
