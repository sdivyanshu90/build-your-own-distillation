"""Pipeline execution use case — runs a queued job to completion.

Invoked by the Celery worker (or inline in eager mode). Responsibilities:

* transition the job ``QUEUED -> RUNNING`` and stream progress to the store;
* invoke the distillation engine in an isolated working directory;
* upload the resulting artifacts to durable storage and record them;
* transition to ``SUCCEEDED``/``FAILED`` and publish the corresponding events.

All persistence happens in short transactions so progress is visible to API
clients while the (potentially long) training runs.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from distillery.domain.entities import Artifact, DistillationJob
from distillery.domain.enums import JobStatus
from distillery.domain.exceptions import DistilleryError, JobNotFoundError
from distillery.domain.ports import (
    ArtifactStorage,
    DistillationEngine,
    EngineArtifact,
    EventPublisher,
    UnitOfWork,
)
from distillery.domain.value_objects import JobProgress
from distillery.infrastructure.observability.metrics import METRICS, Metrics
from distillery.infrastructure.storage.base import compute_checksum, directory_size

logger = logging.getLogger(__name__)

_PROGRESS_MIN_PERCENT_DELTA = 5.0
_PROGRESS_MIN_SECONDS = 3.0


class PipelineService:
    """Executes a single distillation job end-to-end."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        storage: ArtifactStorage,
        engine: DistillationEngine,
        event_publisher: EventPublisher,
        *,
        metrics: Metrics = METRICS,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._engine = engine
        self._events = event_publisher
        self._metrics = metrics

    def run_job(self, job_id: str) -> None:
        job = self._start(job_id)
        if job is None:
            return

        self._metrics.jobs_in_progress.inc()
        try:
            with tempfile.TemporaryDirectory(prefix=f"distillery-{job_id}-") as tmp:
                result = self._engine.run(
                    job.config,
                    work_dir=Path(tmp),
                    on_progress=self._make_progress_callback(job_id),
                )
                artifacts = self._persist_artifacts(job_id, result.artifacts)
            self._finish_success(job_id, result, artifacts)
        except Exception as exc:
            self._finish_failure(job_id, exc)
        finally:
            self._metrics.jobs_in_progress.dec()

    # -- lifecycle steps ---------------------------------------------------
    def _start(self, job_id: str) -> DistillationJob | None:
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(details={"job_id": job_id})
            if job.status is not JobStatus.QUEUED:
                logger.warning("Job %s is %s, not QUEUED; skipping", job_id, job.status.value)
                return None
            job.mark_running()
            uow.jobs.update(job)
            events = job.pull_events()
            uow.commit()
        self._events.publish(events)
        logger.info("Job %s started", job_id)
        return job

    def _finish_success(self, job_id: str, result: object, artifacts: list[Artifact]) -> None:
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None or job.status is not JobStatus.RUNNING:
                logger.warning("Job %s no longer running at completion; discarding", job_id)
                return
            job.mark_succeeded(result.evaluation, result.resource_usage, artifacts)  # type: ignore[attr-defined]
            uow.jobs.update(job)
            events = job.pull_events()
            uow.commit()
        self._metrics.jobs_finished_total.labels(status=JobStatus.SUCCEEDED.value).inc()
        self._metrics.job_duration_seconds.observe(result.resource_usage.duration_seconds)  # type: ignore[attr-defined]
        if result.resource_usage.teacher_tokens:  # type: ignore[attr-defined]
            self._metrics.llm_teacher_tokens_total.inc(result.resource_usage.teacher_tokens)  # type: ignore[attr-defined]
        self._events.publish(events)
        logger.info("Job %s succeeded", job_id)

    def _finish_failure(self, job_id: str, exc: Exception) -> None:
        message = exc.message if isinstance(exc, DistilleryError) else str(exc)
        logger.exception("Job %s failed: %s", job_id, message)
        with self._uow_factory() as uow:
            job = uow.jobs.get(job_id)
            if job is None or job.status.is_terminal:
                return
            job.mark_failed(message)
            uow.jobs.update(job)
            events = job.pull_events()
            uow.commit()
        self._metrics.jobs_finished_total.labels(status=JobStatus.FAILED.value).inc()
        self._events.publish(events)

    # -- helpers -----------------------------------------------------------
    def _make_progress_callback(self, job_id: str) -> Callable[[JobProgress], None]:
        state = {"last_percent": -100.0, "last_time": 0.0}

        def callback(progress: JobProgress) -> None:
            now = time.monotonic()
            advanced = progress.percent - state["last_percent"] >= _PROGRESS_MIN_PERCENT_DELTA
            stale = now - state["last_time"] >= _PROGRESS_MIN_SECONDS
            if not (advanced or stale):
                return
            state["last_percent"] = progress.percent
            state["last_time"] = now
            try:
                with self._uow_factory() as uow:
                    job = uow.jobs.get(job_id)
                    if job is None or job.status is not JobStatus.RUNNING:
                        return
                    job.update_progress(progress)
                    uow.jobs.update(job)
                    uow.commit()
            except Exception:
                logger.debug("Progress update skipped for job %s", job_id)

        return callback

    def _persist_artifacts(
        self, job_id: str, engine_artifacts: list[EngineArtifact]
    ) -> list[Artifact]:
        artifacts: list[Artifact] = []
        base = f"jobs/{job_id}"
        for ea in engine_artifacts:
            path = ea.local_path
            if path.is_dir():
                key = f"{base}/{ea.type.value}"
                uri = self._storage.save_directory(path, key)
                checksum = None
            else:
                key = f"{base}/{ea.type.value}/{path.name}"
                uri = self._storage.save_file(path, key)
                checksum = compute_checksum(path)
            artifacts.append(
                Artifact(
                    job_id=job_id,
                    type=ea.type,
                    uri=uri,
                    size_bytes=directory_size(path),
                    checksum=checksum,
                    metadata=dict(ea.metadata),
                )
            )
        return artifacts
