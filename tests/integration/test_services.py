"""Integration tests for application services (job, pipeline, auth)."""

from __future__ import annotations

from pathlib import Path

import pytest

from distillery.application.services.auth_service import AuthService
from distillery.application.services.job_service import JobService
from distillery.application.services.pipeline_service import PipelineService
from distillery.config.settings import SecuritySettings
from distillery.domain.entities import DistillationJob
from distillery.domain.enums import ArtifactType, JobStatus, Role
from distillery.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    JobNotFoundError,
)
from distillery.domain.ports import EngineArtifact, EngineResult
from distillery.domain.value_objects import EvaluationReport, JobProgress, ResourceUsage
from distillery.infrastructure.events import CollectingEventPublisher

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# JobService (recording queue — no real execution)
# ---------------------------------------------------------------------------
def test_job_service_lifecycle(
    uow_factory, recording_queue, local_storage, response_config
) -> None:
    pub = CollectingEventPublisher()
    svc = JobService(uow_factory, recording_queue, pub, storage=local_storage)

    job = svc.create_job(name="n", config=response_config, owner_id="u1")
    assert job.status is JobStatus.QUEUED
    assert recording_queue.enqueued == [job.id]
    assert job.task_id == f"task-{job.id}"

    assert svc.get_job(job.id).id == job.id
    assert svc.list_jobs(owner_id="u1").total == 1

    cancelled = svc.cancel_job(job.id)
    assert cancelled.status is JobStatus.CANCELLED
    assert recording_queue.cancelled == [cancelled.task_id]

    with pytest.raises(ConflictError):
        svc.cancel_job(job.id)  # already terminal

    svc.delete_job(job.id)
    with pytest.raises(JobNotFoundError):
        svc.get_job(job.id)


def test_job_service_delete_active_rejected(uow_factory, recording_queue, response_config) -> None:
    svc = JobService(uow_factory, recording_queue, CollectingEventPublisher())
    job = svc.create_job(name="n", config=response_config, owner_id="u1")
    with pytest.raises(ConflictError):
        svc.delete_job(job.id)  # still QUEUED


def test_job_service_missing_raises(uow_factory, recording_queue) -> None:
    svc = JobService(uow_factory, recording_queue, CollectingEventPublisher())
    with pytest.raises(JobNotFoundError):
        svc.get_job("nope")


# ---------------------------------------------------------------------------
# PipelineService (fake engine — deterministic, no torch)
# ---------------------------------------------------------------------------
class _FakeEngine:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def run(self, config, *, work_dir: Path, on_progress=None) -> EngineResult:
        if on_progress:
            on_progress(JobProgress(current_step=1, total_steps=1, message="done"))
        if self.fail:
            raise RuntimeError("kaboom")
        report_file = work_dir / "report.json"
        report_file.write_text("{}", encoding="utf-8")
        model_dir = work_dir / "student_model"
        model_dir.mkdir()
        (model_dir / "weights.bin").write_bytes(b"\x00")
        return EngineResult(
            evaluation=EvaluationReport(student_metrics={"accuracy": 0.8}),
            resource_usage=ResourceUsage(duration_seconds=0.1, teacher_tokens=10),
            artifacts=[
                EngineArtifact(ArtifactType.EVALUATION_REPORT, report_file),
                EngineArtifact(ArtifactType.STUDENT_MODEL, model_dir),
            ],
        )


def _queued_job(uow_factory, response_config) -> str:
    job = DistillationJob(name="p", config=response_config, owner_id="u1")
    job.mark_queued("t1")
    with uow_factory() as uow:
        uow.jobs.add(job)
        uow.commit()
    return job.id


def test_pipeline_success(uow_factory, local_storage, response_config) -> None:
    jid = _queued_job(uow_factory, response_config)
    pub = CollectingEventPublisher()
    PipelineService(uow_factory, local_storage, _FakeEngine(), pub).run_job(jid)

    with uow_factory() as uow:
        job = uow.jobs.get(jid)
    assert job.status is JobStatus.SUCCEEDED
    assert job.evaluation.student_metrics["accuracy"] == 0.8
    assert {a.type for a in job.artifacts} == {
        ArtifactType.EVALUATION_REPORT,
        ArtifactType.STUDENT_MODEL,
    }
    assert local_storage.exists(f"jobs/{jid}/evaluation_report/report.json")
    assert local_storage.exists(f"jobs/{jid}/student_model")
    assert any(e.name == "JobCompleted" for e in pub.events)


def test_pipeline_failure_marks_failed(uow_factory, local_storage, response_config) -> None:
    jid = _queued_job(uow_factory, response_config)
    PipelineService(
        uow_factory, local_storage, _FakeEngine(fail=True), CollectingEventPublisher()
    ).run_job(jid)
    with uow_factory() as uow:
        job = uow.jobs.get(jid)
    assert job.status is JobStatus.FAILED
    assert "kaboom" in job.error


def test_pipeline_skips_non_queued(uow_factory, local_storage, response_config) -> None:
    job = DistillationJob(name="p", config=response_config, owner_id="u1")  # PENDING
    with uow_factory() as uow:
        uow.jobs.add(job)
        uow.commit()
    # Should no-op without raising.
    PipelineService(uow_factory, local_storage, _FakeEngine(), CollectingEventPublisher()).run_job(
        job.id
    )
    with uow_factory() as uow:
        assert uow.jobs.get(job.id).status is JobStatus.PENDING


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_service(uow_factory) -> AuthService:
    return AuthService(
        uow_factory, SecuritySettings(jwt_secret="x" * 40, password_hash_iterations=100_000)
    )


def test_auth_create_and_login(auth_service: AuthService) -> None:
    user = auth_service.create_user(email="A@X.io", password="longenoughpw123", role=Role.OPERATOR)
    assert user.email == "a@x.io"
    token = auth_service.login("a@x.io", "longenoughpw123")
    assert token


def test_auth_duplicate_user(auth_service: AuthService) -> None:
    auth_service.create_user(email="a@x.io", password="longenoughpw123")
    with pytest.raises(ConflictError):
        auth_service.create_user(email="a@x.io", password="longenoughpw123")


def test_auth_bad_login(auth_service: AuthService) -> None:
    auth_service.create_user(email="a@x.io", password="longenoughpw123")
    with pytest.raises(AuthenticationError):
        auth_service.login("a@x.io", "wrong-password")
    with pytest.raises(AuthenticationError):
        auth_service.login("missing@x.io", "whatever12345")


def test_auth_create_api_key(auth_service: AuthService) -> None:
    user = auth_service.create_user(email="a@x.io", password="longenoughpw123", role=Role.ADMIN)
    api_key, secret = auth_service.create_api_key(owner_id=user.id, name="k", role=Role.OPERATOR)
    assert secret.startswith("dst_")
    assert api_key.prefix
    assert len(auth_service.list_api_keys(user.id)) == 1


def test_auth_api_key_unknown_owner(auth_service: AuthService) -> None:
    with pytest.raises(AuthenticationError):
        auth_service.create_api_key(owner_id="ghost", name="k")
