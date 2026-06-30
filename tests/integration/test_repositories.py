"""Integration tests for SQLAlchemy repositories and the Unit of Work."""

from __future__ import annotations

import pytest

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User
from distillery.domain.enums import (
    ArtifactType,
    DatasetFormat,
    DistillationStrategy,
    JobStatus,
    Role,
    TeacherType,
)
from distillery.domain.exceptions import JobNotFoundError
from distillery.domain.value_objects import (
    DatasetSpec,
    DistillationConfig,
    EvaluationReport,
    ModelSpec,
    ResourceUsage,
)

pytestmark = pytest.mark.integration


def _config() -> DistillationConfig:
    return DistillationConfig(
        strategy=DistillationStrategy.RESPONSE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=ModelSpec(name_or_path="t", num_labels=2),
        student=ModelSpec(name_or_path="s", num_labels=2),
        dataset=DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "a", "label": 0}]),
    )


def test_job_round_trip(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io", role=Role.OPERATOR))
        job = DistillationJob(name="j", config=_config(), owner_id=user.id)
        uow.jobs.add(job)
        uow.commit()
        job_id = job.id

    with uow_factory() as uow:
        loaded = uow.jobs.get(job_id)
        assert loaded is not None
        assert loaded.config.strategy is DistillationStrategy.RESPONSE_BASED


def test_job_update_persists_artifacts_and_eval(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        job = DistillationJob(name="j", config=_config(), owner_id=user.id)
        uow.jobs.add(job)
        uow.commit()
        jid = job.id

    with uow_factory() as uow:
        job = uow.jobs.get(jid)
        job.mark_queued("t1")
        job.mark_running()
        job.add_artifact(Artifact(job_id=jid, type=ArtifactType.STUDENT_MODEL, uri="file:///m"))
        job.mark_succeeded(
            EvaluationReport(student_metrics={"accuracy": 0.88}), ResourceUsage(duration_seconds=2)
        )
        uow.jobs.update(job)
        uow.commit()

    with uow_factory() as uow:
        job = uow.jobs.get(jid)
        assert job.status is JobStatus.SUCCEEDED
        assert job.evaluation.student_metrics["accuracy"] == 0.88
        assert len(job.artifacts) == 1


def test_list_filters_and_pagination(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        for i in range(5):
            job = DistillationJob(name=f"j{i}", config=_config(), owner_id=user.id)
            if i % 2 == 0:
                job.mark_queued()
            uow.jobs.add(job)
            uow.jobs.update(job) if i % 2 == 0 else None
        uow.commit()
        uid = user.id

    with uow_factory() as uow:
        assert uow.jobs.count(owner_id=uid) == 5
        assert uow.jobs.count(owner_id=uid, status=JobStatus.QUEUED) == 3
        page = uow.jobs.list(owner_id=uid, limit=2, offset=0)
        assert len(page) == 2


def test_update_missing_job_raises(uow_factory) -> None:
    job = DistillationJob(name="ghost", config=_config(), owner_id="nobody")
    with uow_factory() as uow, pytest.raises(JobNotFoundError):
        uow.jobs.update(job)


def test_delete_job(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        job = DistillationJob(name="j", config=_config(), owner_id=user.id)
        uow.jobs.add(job)
        uow.commit()
        jid = job.id
    with uow_factory() as uow:
        uow.jobs.delete(jid)
        uow.commit()
    with uow_factory() as uow:
        assert uow.jobs.get(jid) is None


def test_user_repository(uow_factory) -> None:
    with uow_factory() as uow:
        uow.users.add(User(email="a@x.io", role=Role.ADMIN))
        uow.commit()
    with uow_factory() as uow:
        found = uow.users.get_by_email("a@x.io")
        assert found is not None and found.role is Role.ADMIN
        assert uow.users.get_by_email("missing@x.io") is None
        assert len(uow.users.list()) == 1


def test_api_key_repository(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        key = ApiKey(name="k", prefix="abc1234567", hashed_key="h", owner_id=user.id)
        uow.api_keys.add(key)
        uow.commit()
        kid, uid = key.id, user.id

    with uow_factory() as uow:
        found = uow.api_keys.get_by_prefix("abc1234567")
        assert found is not None and found.id == kid
        found.is_active = False
        uow.api_keys.update(found)
        uow.commit()

    with uow_factory() as uow:
        assert uow.api_keys.get_by_prefix("abc1234567").is_active is False
        assert len(uow.api_keys.list_for_owner(uid)) == 1


def test_artifact_repository(uow_factory) -> None:
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        job = DistillationJob(name="j", config=_config(), owner_id=user.id)
        uow.jobs.add(job)
        art = uow.artifacts.add(
            Artifact(job_id=job.id, type=ArtifactType.TRAINING_LOG, uri="file:///l")
        )
        uow.commit()
        aid, jid = art.id, job.id
    with uow_factory() as uow:
        assert uow.artifacts.get(aid) is not None
        assert len(uow.artifacts.list_for_job(jid)) == 1
