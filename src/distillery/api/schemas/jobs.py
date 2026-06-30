"""Job request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from distillery.domain.entities import Artifact, DistillationJob
from distillery.domain.enums import ArtifactType, JobStatus
from distillery.domain.value_objects import (
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    ResourceUsage,
)


class JobCreateRequest(BaseModel):
    """Payload to create a distillation job."""

    name: str = Field(..., min_length=1, max_length=256, examples=["distilbert-sst2"])
    config: DistillationConfig


class ArtifactResponse(BaseModel):
    id: str
    type: ArtifactType
    uri: str
    size_bytes: int
    checksum: str | None
    metadata: dict[str, str]
    created_at: datetime

    @classmethod
    def from_entity(cls, a: Artifact) -> ArtifactResponse:
        return cls(
            id=a.id,
            type=a.type,
            uri=a.uri,
            size_bytes=a.size_bytes,
            checksum=a.checksum,
            metadata=a.metadata,
            created_at=a.created_at,
        )


class EvaluationResponse(BaseModel):
    """Evaluation results including derived headline metrics."""

    student_metrics: dict[str, float]
    teacher_metrics: dict[str, float]
    teacher_agreement: float
    student_latency_ms: float
    teacher_latency_ms: float
    teacher_params: int
    student_params: int
    compression_ratio: float
    size_reduction_percent: float
    primary_metric: float
    teacher_accuracy_retention: float

    @classmethod
    def from_report(cls, report: EvaluationReport) -> EvaluationResponse:
        return cls(
            student_metrics=report.student_metrics,
            teacher_metrics=report.teacher_metrics,
            teacher_agreement=report.teacher_agreement,
            student_latency_ms=report.student_latency_ms,
            teacher_latency_ms=report.teacher_latency_ms,
            teacher_params=report.compression.teacher_params,
            student_params=report.compression.student_params,
            compression_ratio=report.compression.compression_ratio,
            size_reduction_percent=report.compression.size_reduction_percent,
            primary_metric=report.primary_metric,
            teacher_accuracy_retention=report.retention,
        )


class JobResponse(BaseModel):
    """Full representation of a distillation job."""

    id: str
    name: str
    owner_id: str
    status: JobStatus
    config: DistillationConfig
    progress: JobProgress
    progress_percent: float
    evaluation: EvaluationResponse | None
    resource_usage: ResourceUsage | None
    error: str | None
    task_id: str | None
    artifacts: list[ArtifactResponse]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_entity(cls, job: DistillationJob) -> JobResponse:
        return cls(
            id=job.id,
            name=job.name,
            owner_id=job.owner_id,
            status=job.status,
            config=job.config,
            progress=job.progress,
            progress_percent=job.progress.percent,
            evaluation=EvaluationResponse.from_report(job.evaluation) if job.evaluation else None,
            resource_usage=job.resource_usage,
            error=job.error,
            task_id=job.task_id,
            artifacts=[ArtifactResponse.from_entity(a) for a in job.artifacts],
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
