"""Job management use cases (create / read / list / cancel / delete)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from distillery.application.dto import Page
from distillery.domain.entities import DistillationJob
from distillery.domain.enums import JobStatus
from distillery.domain.exceptions import ConflictError, JobNotFoundError
from distillery.domain.ports import (
    ArtifactStorage,
    EventPublisher,
    TaskQueue,
    UnitOfWork,
)
from distillery.domain.value_objects import DistillationConfig
from distillery.infrastructure.observability.metrics import METRICS, Metrics

logger = logging.getLogger(__name__)


class JobService:
    """Coordinates the lifecycle of distillation jobs."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        task_queue: TaskQueue,
        event_publisher: EventPublisher,
        *,
        storage: ArtifactStorage | None = None,
        metrics: Metrics = METRICS,
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = task_queue
        self._events = event_publisher
        self._storage = storage
        self._metrics = metrics

    def create_job(
        self, *, name: str, config: DistillationConfig, owner_id: str
    ) -> DistillationJob:
        """Persist a new job, enqueue it for execution and return it (QUEUED)."""
        job = DistillationJob(name=name, config=config, owner_id=owner_id)

        # 1. Persist as QUEUED first so the worker always finds a committed row.
        with self._uow_factory() as uow:
            uow.jobs.add(job)
            job.mark_queued()
            uow.jobs.update(job)
            uow.commit()

        # 2. Schedule execution (may run inline in eager mode).
        task_id = self._queue.enqueue_distillation(job.id)

        # 3. Record the task id if still queued, then return fresh state. (In
        # eager mode the inline run above may already have finished the job.)
        with self._uow_factory() as uow:
            persisted = uow.jobs.get(job.id)
            if persisted and persisted.status is JobStatus.QUEUED:
                persisted.task_id = task_id
                uow.jobs.update(persisted)
                uow.commit()
            if persisted is not None:
                job = persisted

        self._metrics.jobs_created_total.labels(strategy=config.strategy.value).inc()
        self._events.publish(job.pull_events())
        logger.info("Created job %s (%s)", job.id, config.strategy.value)
        return job

    def get_job(self, job_id: str) -> DistillationJob:
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(details={"job_id": job_id})
            return job

    def list_jobs(
        self,
        *,
        owner_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[DistillationJob]:
        with self._uow_factory() as uow:
            items = list(
                uow.jobs.list(owner_id=owner_id, status=status, limit=limit, offset=offset)
            )
            total = uow.jobs.count(owner_id=owner_id, status=status)
            return Page(items=items, total=total, limit=limit, offset=offset)

    def cancel_job(self, job_id: str) -> DistillationJob:
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(details={"job_id": job_id})
            if job.status.is_terminal:
                raise ConflictError(f"Job is already {job.status.value} and cannot be cancelled")
            if job.task_id:
                self._queue.cancel(job.task_id)
            job.cancel()
            uow.jobs.update(job)
            events = job.pull_events()
            uow.commit()
        self._metrics.jobs_finished_total.labels(status=JobStatus.CANCELLED.value).inc()
        self._events.publish(events)
        return job

    def delete_job(self, job_id: str) -> None:
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(details={"job_id": job_id})
            if job.status.is_active:
                raise ConflictError("Cancel the job before deleting it")
            uow.jobs.delete(job_id)
            uow.commit()
        if self._storage is not None:
            try:
                self._storage.delete(f"jobs/{job_id}")
            except Exception:
                logger.warning("Failed to delete artifacts for job %s", job_id)
