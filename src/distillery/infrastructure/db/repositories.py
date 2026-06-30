"""SQLAlchemy repository and Unit-of-Work implementations.

These satisfy the repository/UoW *ports* declared in
:mod:`distillery.domain.ports`. The UoW gives application services a single
atomic transaction spanning multiple repositories; exiting the context without
an explicit :meth:`commit` rolls back.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from distillery.domain.entities import ApiKey, Artifact, DistillationJob, User
from distillery.domain.enums import JobStatus
from distillery.domain.exceptions import JobNotFoundError
from distillery.infrastructure.db.mappers import (
    apikey_to_domain,
    apikey_to_orm,
    apply_job_to_orm,
    artifact_to_domain,
    artifact_to_orm,
    job_to_domain,
    job_to_orm,
    user_to_domain,
    user_to_orm,
)
from distillery.infrastructure.db.models import (
    ApiKeyModel,
    ArtifactModel,
    JobModel,
    UserModel,
)


class SqlAlchemyJobRepository:
    """Persistence for :class:`DistillationJob` aggregates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: DistillationJob) -> DistillationJob:
        orm = job_to_orm(job)
        self._session.add(orm)
        for artifact in job.artifacts:
            self._session.add(artifact_to_orm(artifact))
        self._session.flush()
        return job

    def get(self, job_id: str) -> DistillationJob | None:
        orm = self._session.get(JobModel, job_id, options=[selectinload(JobModel.artifacts)])
        return job_to_domain(orm) if orm else None

    def update(self, job: DistillationJob) -> DistillationJob:
        orm = self._session.get(JobModel, job.id, options=[selectinload(JobModel.artifacts)])
        if orm is None:
            raise JobNotFoundError(details={"job_id": job.id})
        apply_job_to_orm(job, orm)
        existing = {a.id for a in orm.artifacts}
        for artifact in job.artifacts:
            if artifact.id not in existing:
                self._session.add(artifact_to_orm(artifact))
        self._session.flush()
        return job

    def delete(self, job_id: str) -> None:
        orm = self._session.get(JobModel, job_id)
        if orm is not None:
            self._session.delete(orm)
            self._session.flush()

    def list(
        self,
        *,
        owner_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[DistillationJob]:
        stmt = select(JobModel).options(selectinload(JobModel.artifacts))
        if owner_id is not None:
            stmt = stmt.where(JobModel.owner_id == owner_id)
        if status is not None:
            stmt = stmt.where(JobModel.status == status.value)
        stmt = stmt.order_by(JobModel.created_at.desc()).limit(limit).offset(offset)
        return [job_to_domain(o) for o in self._session.scalars(stmt).unique().all()]

    def count(self, *, owner_id: str | None = None, status: JobStatus | None = None) -> int:
        stmt = select(func.count()).select_from(JobModel)
        if owner_id is not None:
            stmt = stmt.where(JobModel.owner_id == owner_id)
        if status is not None:
            stmt = stmt.where(JobModel.status == status.value)
        return int(self._session.scalar(stmt) or 0)


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> User:
        self._session.add(user_to_orm(user))
        self._session.flush()
        return user

    def get(self, user_id: str) -> User | None:
        orm = self._session.get(UserModel, user_id)
        return user_to_domain(orm) if orm else None

    def get_by_email(self, email: str) -> User | None:
        orm = self._session.scalar(select(UserModel).where(UserModel.email == email))
        return user_to_domain(orm) if orm else None

    def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[User]:
        stmt = select(UserModel).order_by(UserModel.created_at).limit(limit).offset(offset)
        return [user_to_domain(o) for o in self._session.scalars(stmt).all()]


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, api_key: ApiKey) -> ApiKey:
        self._session.add(apikey_to_orm(api_key))
        self._session.flush()
        return api_key

    def get_by_prefix(self, prefix: str) -> ApiKey | None:
        orm = self._session.scalar(select(ApiKeyModel).where(ApiKeyModel.prefix == prefix))
        return apikey_to_domain(orm) if orm else None

    def update(self, api_key: ApiKey) -> ApiKey:
        orm = self._session.get(ApiKeyModel, api_key.id)
        if orm is None:
            self._session.add(apikey_to_orm(api_key))
        else:
            orm.is_active = api_key.is_active
            orm.last_used_at = api_key.last_used_at
            orm.expires_at = api_key.expires_at
            orm.role = api_key.role.value
        self._session.flush()
        return api_key

    def list_for_owner(self, owner_id: str) -> Sequence[ApiKey]:
        stmt = select(ApiKeyModel).where(ApiKeyModel.owner_id == owner_id)
        return [apikey_to_domain(o) for o in self._session.scalars(stmt).all()]


class SqlAlchemyArtifactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, artifact: Artifact) -> Artifact:
        self._session.add(artifact_to_orm(artifact))
        self._session.flush()
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        orm = self._session.get(ArtifactModel, artifact_id)
        return artifact_to_domain(orm) if orm else None

    def list_for_job(self, job_id: str) -> Sequence[Artifact]:
        stmt = select(ArtifactModel).where(ArtifactModel.job_id == job_id)
        return [artifact_to_domain(o) for o in self._session.scalars(stmt).all()]


class SqlAlchemyUnitOfWork:
    """A transactional Unit of Work aggregating the SQLAlchemy repositories."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._committed = False

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self.session: Session = self._session_factory()
        self.jobs = SqlAlchemyJobRepository(self.session)
        self.users = SqlAlchemyUserRepository(self.session)
        self.api_keys = SqlAlchemyApiKeyRepository(self.session)
        self.artifacts = SqlAlchemyArtifactRepository(self.session)
        self._committed = False
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        try:
            if exc_type is not None or not self._committed:
                self.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        self.session.rollback()
