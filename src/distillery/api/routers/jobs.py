"""Distillation job endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from distillery.api.deps import (
    JobServiceDep,
    PrincipalDep,
    authorize_job_access,
    get_current_principal,
    require_role,
)
from distillery.api.schemas.jobs import (
    ArtifactResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from distillery.domain.enums import JobStatus, Role

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_principal)])


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create and enqueue a distillation job",
)
def create_job(
    payload: JobCreateRequest,
    jobs: JobServiceDep,
    principal: Annotated[object, Depends(require_role(Role.OPERATOR))],
) -> JobResponse:
    job = jobs.create_job(
        name=payload.name, config=payload.config, owner_id=principal.subject  # type: ignore[attr-defined]
    )
    return JobResponse.from_entity(job)


@router.get("", response_model=JobListResponse, summary="List distillation jobs")
def list_jobs(
    jobs: JobServiceDep,
    principal: PrincipalDep,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    mine: Annotated[bool, Query(description="Restrict to your own jobs.")] = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    owner_filter = None if (principal.role is Role.ADMIN and not mine) else principal.subject
    page = jobs.list_jobs(owner_id=owner_filter, status=status_filter, limit=limit, offset=offset)
    return JobListResponse(
        items=[JobResponse.from_entity(j) for j in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


@router.get("/{job_id}", response_model=JobResponse, summary="Get a job by id")
def get_job(job_id: str, jobs: JobServiceDep, principal: PrincipalDep) -> JobResponse:
    job = jobs.get_job(job_id)
    authorize_job_access(job, principal)
    return JobResponse.from_entity(job)


@router.get(
    "/{job_id}/artifacts",
    response_model=list[ArtifactResponse],
    summary="List a job's artifacts",
)
def list_artifacts(
    job_id: str, jobs: JobServiceDep, principal: PrincipalDep
) -> list[ArtifactResponse]:
    job = jobs.get_job(job_id)
    authorize_job_access(job, principal)
    return [ArtifactResponse.from_entity(a) for a in job.artifacts]


@router.post("/{job_id}/cancel", response_model=JobResponse, summary="Cancel a job")
def cancel_job(
    job_id: str,
    jobs: JobServiceDep,
    principal: Annotated[object, Depends(require_role(Role.OPERATOR))],
) -> JobResponse:
    job = jobs.get_job(job_id)
    authorize_job_access(job, principal)  # type: ignore[arg-type]
    return JobResponse.from_entity(jobs.cancel_job(job_id))


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a terminal job",
)
def delete_job(
    job_id: str,
    jobs: JobServiceDep,
    principal: Annotated[object, Depends(require_role(Role.OPERATOR))],
) -> Response:
    job = jobs.get_job(job_id)
    authorize_job_access(job, principal)  # type: ignore[arg-type]
    jobs.delete_job(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
