"""``TaskQueue`` port adapters: Celery (production) and inline (dev/tests)."""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class CeleryTaskQueue:  # pragma: no cover - requires a live broker (integration/CD)
    """Schedules jobs via Celery. Imports Celery lazily so the API request path
    that merely *constructs* this adapter does not pull Celery in."""

    def enqueue_distillation(self, job_id: str) -> str:
        from distillery.infrastructure.queue.tasks import run_distillation_job

        async_result = run_distillation_job.delay(job_id)
        logger.info("Enqueued job %s as task %s", job_id, async_result.id)
        return str(async_result.id)

    def cancel(self, task_id: str) -> None:
        from distillery.infrastructure.queue.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        logger.info("Revoked task %s", task_id)


class InlineTaskQueue:
    """Executes jobs synchronously in-process (eager mode / e2e tests)."""

    def __init__(self, runner: Callable[[str], None]) -> None:
        self._runner = runner

    def enqueue_distillation(self, job_id: str) -> str:
        self._runner(job_id)
        return f"inline-{job_id}"

    def cancel(self, task_id: str) -> None:
        return None
