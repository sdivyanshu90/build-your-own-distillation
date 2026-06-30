"""Bidirectional mapping between ORM models and domain entities.

Keeping mapping explicit (rather than using the ORM objects as domain objects)
preserves persistence ignorance: the domain never imports SQLAlchemy and can be
unit-tested without a database.
"""

from __future__ import annotations

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User
from distillery.domain.enums import ArtifactType, JobStatus, Role
from distillery.domain.value_objects import (
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    ResourceUsage,
)
from distillery.infrastructure.db.models import (
    ApiKeyModel,
    ArtifactModel,
    JobModel,
    UserModel,
)


# -- User --------------------------------------------------------------------
def user_to_domain(orm: UserModel) -> User:
    return User(
        id=orm.id,
        email=orm.email,
        role=Role(orm.role),
        hashed_password=orm.hashed_password,
        is_active=orm.is_active,
        created_at=orm.created_at,
    )


def user_to_orm(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=user.email,
        role=user.role.value,
        hashed_password=user.hashed_password,
        is_active=user.is_active,
    )


# -- ApiKey ------------------------------------------------------------------
def apikey_to_domain(orm: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=orm.id,
        name=orm.name,
        prefix=orm.prefix,
        hashed_key=orm.hashed_key,
        owner_id=orm.owner_id,
        role=Role(orm.role),
        is_active=orm.is_active,
        created_at=orm.created_at,
        last_used_at=orm.last_used_at,
        expires_at=orm.expires_at,
    )


def apikey_to_orm(api_key: ApiKey) -> ApiKeyModel:
    return ApiKeyModel(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        hashed_key=api_key.hashed_key,
        owner_id=api_key.owner_id,
        role=api_key.role.value,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
    )


# -- Artifact ----------------------------------------------------------------
def artifact_to_domain(orm: ArtifactModel) -> Artifact:
    return Artifact(
        id=orm.id,
        job_id=orm.job_id,
        type=ArtifactType(orm.type),
        uri=orm.uri,
        size_bytes=orm.size_bytes,
        checksum=orm.checksum,
        metadata=dict(orm.artifact_metadata or {}),
        created_at=orm.created_at,
    )


def artifact_to_orm(artifact: Artifact) -> ArtifactModel:
    return ArtifactModel(
        id=artifact.id,
        job_id=artifact.job_id,
        type=artifact.type.value,
        uri=artifact.uri,
        size_bytes=artifact.size_bytes,
        checksum=artifact.checksum,
        artifact_metadata=dict(artifact.metadata),
    )


# -- Job ---------------------------------------------------------------------
def job_to_domain(orm: JobModel) -> DistillationJob:
    return DistillationJob(
        id=orm.id,
        name=orm.name,
        owner_id=orm.owner_id,
        status=JobStatus(orm.status),
        config=DistillationConfig.model_validate(orm.config),
        progress=JobProgress.model_validate(orm.progress) if orm.progress else JobProgress(),
        evaluation=EvaluationReport.model_validate(orm.evaluation) if orm.evaluation else None,
        resource_usage=(
            ResourceUsage.model_validate(orm.resource_usage) if orm.resource_usage else None
        ),
        error=orm.error,
        task_id=orm.task_id,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        artifacts=[artifact_to_domain(a) for a in orm.artifacts],
    )


def job_to_orm(job: DistillationJob) -> JobModel:
    return JobModel(
        id=job.id,
        name=job.name,
        owner_id=job.owner_id,
        status=job.status.value,
        config=job.config.model_dump(mode="json"),
        progress=job.progress.model_dump(mode="json"),
        evaluation=job.evaluation.model_dump(mode="json") if job.evaluation else None,
        resource_usage=(job.resource_usage.model_dump(mode="json") if job.resource_usage else None),
        error=job.error,
        task_id=job.task_id,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def apply_job_to_orm(job: DistillationJob, orm: JobModel) -> None:
    """Copy mutable domain state onto an existing ORM row (for updates)."""
    orm.name = job.name
    orm.status = job.status.value
    orm.config = job.config.model_dump(mode="json")
    orm.progress = job.progress.model_dump(mode="json")
    orm.evaluation = job.evaluation.model_dump(mode="json") if job.evaluation else None
    orm.resource_usage = job.resource_usage.model_dump(mode="json") if job.resource_usage else None
    orm.error = job.error
    orm.task_id = job.task_id
    orm.started_at = job.started_at
    orm.finished_at = job.finished_at
