"""Unit tests for domain entities and the job state machine."""

from __future__ import annotations

import pytest

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User, _utcnow
from distillery.domain.enums import (
    ArtifactType,
    DatasetFormat,
    DistillationStrategy,
    JobStatus,
    Role,
    TeacherType,
)
from distillery.domain.events import JobCompleted, JobFailed, JobStarted
from distillery.domain.exceptions import InvalidStateTransitionError
from distillery.domain.value_objects import (
    DatasetSpec,
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    ModelSpec,
    ResourceUsage,
)

pytestmark = pytest.mark.unit


def _config() -> DistillationConfig:
    return DistillationConfig(
        strategy=DistillationStrategy.RESPONSE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=ModelSpec(name_or_path="t", num_labels=2),
        student=ModelSpec(name_or_path="s", num_labels=2),
        dataset=DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "a", "label": 0}]),
    )


@pytest.fixture
def job() -> DistillationJob:
    return DistillationJob(name="j", config=_config(), owner_id="owner-1")


def test_new_job_is_pending(job: DistillationJob) -> None:
    assert job.status is JobStatus.PENDING
    assert job.id
    assert job.progress.percent == 0.0


def test_happy_path_lifecycle(job: DistillationJob) -> None:
    job.mark_queued("task-1")
    assert job.status is JobStatus.QUEUED
    assert job.task_id == "task-1"

    job.mark_running()
    assert job.status is JobStatus.RUNNING
    assert job.started_at is not None

    report = EvaluationReport(student_metrics={"accuracy": 0.9})
    job.mark_succeeded(report, ResourceUsage(duration_seconds=1.0))
    assert job.status is JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.evaluation is report


def test_events_emitted_in_order(job: DistillationJob) -> None:
    job.mark_queued()
    job.mark_running()
    job.update_progress(JobProgress(current_step=1, total_steps=2))
    job.mark_succeeded(EvaluationReport(student_metrics={"accuracy": 1.0}), ResourceUsage())
    events = job.pull_events()
    names = [type(e).__name__ for e in events]
    assert names[0] == JobStarted.__name__
    assert "JobProgressed" in names
    assert names[-1] == JobCompleted.__name__
    # Buffer is cleared after pulling.
    assert job.pull_events() == []


def test_failure_records_error_event(job: DistillationJob) -> None:
    job.mark_queued()
    job.mark_running()
    job.mark_failed("boom")
    assert job.status is JobStatus.FAILED
    assert job.error == "boom"
    assert any(isinstance(e, JobFailed) for e in job.pull_events())


@pytest.mark.parametrize(
    "transition",
    [
        lambda j: j.mark_running(),  # PENDING -> RUNNING (illegal)
        lambda j: j.mark_succeeded(EvaluationReport(), ResourceUsage()),
    ],
)
def test_illegal_transitions_rejected(job: DistillationJob, transition) -> None:
    with pytest.raises(InvalidStateTransitionError):
        transition(job)


def test_cannot_transition_from_terminal(job: DistillationJob) -> None:
    job.cancel()
    assert job.status is JobStatus.CANCELLED
    with pytest.raises(InvalidStateTransitionError):
        job.mark_running()


def test_progress_only_while_running(job: DistillationJob) -> None:
    with pytest.raises(InvalidStateTransitionError):
        job.update_progress(JobProgress(current_step=1, total_steps=2))


def test_add_artifact(job: DistillationJob) -> None:
    art = Artifact(job_id=job.id, type=ArtifactType.STUDENT_MODEL, uri="file:///x")
    job.add_artifact(art)
    assert job.artifacts == [art]


def test_user_rbac() -> None:
    admin = User(email="a@x.io", role=Role.ADMIN)
    viewer = User(email="v@x.io", role=Role.VIEWER)
    assert admin.can(Role.OPERATOR)
    assert not viewer.can(Role.OPERATOR)
    assert viewer.can(Role.VIEWER)
    viewer.is_active = False
    assert not viewer.can(Role.VIEWER)


def test_api_key_expiry() -> None:
    from datetime import timedelta

    key = ApiKey(name="k", prefix="p", hashed_key="h", owner_id="o")
    assert key.is_usable
    key.expires_at = _utcnow() - timedelta(seconds=1)
    assert key.is_expired
    assert not key.is_usable
