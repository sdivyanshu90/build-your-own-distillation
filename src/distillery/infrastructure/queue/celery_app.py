"""Celery application factory.

Importing this module requires ``celery`` (install ``distillery[api]``); it is
only imported by the worker entrypoint and lazily by the Celery task queue
adapter, so the API request path never pulls Celery in.
"""

from __future__ import annotations

from celery import Celery

from distillery.config.settings import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create and configure the Celery application."""
    settings = settings or get_settings()
    app = Celery(
        "distillery",
        broker=settings.queue.broker_url,
        backend=settings.queue.result_backend,
        include=["distillery.infrastructure.queue.tasks"],
    )
    app.conf.update(
        task_acks_late=True,  # re-deliver if a worker dies mid-task
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # fair dispatch for long jobs
        worker_concurrency=settings.queue.worker_concurrency,
        task_time_limit=settings.queue.task_time_limit_seconds,
        task_soft_time_limit=settings.queue.task_soft_time_limit_seconds,
        task_track_started=True,
        task_default_retry_delay=30,
        result_expires=86_400,
        broker_transport_options={"visibility_timeout": settings.queue.visibility_timeout_seconds},
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )
    return app


# Module-level app discovered by the Celery CLI: ``celery -A ...celery_app:celery_app``.
celery_app = create_celery_app()
