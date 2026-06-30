"""Enumerations that form the shared vocabulary of the domain."""

from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    """Lifecycle states of a distillation job.

    The legal transitions are enforced by
    :meth:`distillery.domain.entities.DistillationJob.transition_to`.
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}

    @property
    def is_active(self) -> bool:
        return self in {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING}


class DistillationStrategy(str, enum.Enum):
    """The distillation algorithm to apply."""

    #: Match the teacher's softened logits (Hinton et al., 2015) + hard CE.
    RESPONSE_BASED = "response_based"
    #: Response-based plus intermediate hidden-state alignment.
    FEATURE_BASED = "feature_based"
    #: Use an LLM to synthesise/label data, then supervised fine-tune.
    LLM_TEACHER = "llm_teacher"


class ModelTask(str, enum.Enum):
    """The downstream task the student is trained for."""

    SEQUENCE_CLASSIFICATION = "sequence_classification"
    TOKEN_CLASSIFICATION = "token_classification"  # noqa: S105 - an NLP task, not a secret


class TeacherType(str, enum.Enum):
    """The kind of teacher supplying supervision."""

    HUGGINGFACE = "huggingface"
    LLM = "llm"


class DatasetFormat(str, enum.Enum):
    """Supported dataset source formats."""

    HF_HUB = "hf_hub"  # a datasets.load_dataset reference
    JSONL = "jsonl"  # local/remote newline-delimited JSON
    CSV = "csv"
    INLINE = "inline"  # rows embedded directly in the request (tests/small jobs)


class ArtifactType(str, enum.Enum):
    """Categories of artifact produced by a job."""

    STUDENT_MODEL = "student_model"
    EVALUATION_REPORT = "evaluation_report"
    SYNTHETIC_DATASET = "synthetic_dataset"
    TRAINING_LOG = "training_log"
    CONFIG_SNAPSHOT = "config_snapshot"


class Role(str, enum.Enum):
    """Coarse-grained RBAC roles."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        """Higher rank ⇒ strictly more privilege (used for >= checks)."""
        return {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}[self]
