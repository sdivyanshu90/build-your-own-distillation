"""Celery task definitions.

Each task is a thin shim: it binds logging context and delegates to the
application :class:`PipelineService`. Heavy imports (the engine, torch) happen
inside :func:`distillery.bootstrap.build_pipeline_service`, keeping task import
light.
"""

from __future__ import annotations

import logging

from distillery.infrastructure.observability.logging import bind_context, clear_context
from distillery.infrastructure.queue.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="distillery.run_distillation_job",
    bind=True,
    acks_late=True,
    max_retries=0,
)
def run_distillation_job(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    """Execute a queued distillation job to completion."""
    from distillery.bootstrap import build_pipeline_service

    bind_context(job_id=job_id, task_id=self.request.id)
    try:
        logger.info("Worker picked up job %s", job_id)
        build_pipeline_service().run_job(job_id)
        return job_id
    finally:
        clear_context()
