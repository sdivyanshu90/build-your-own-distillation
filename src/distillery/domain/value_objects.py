"""Immutable value objects describing distillation jobs and their results.

Value objects are frozen (hashable, equality-by-value) and self-validating. They
contain no identity and no behaviour beyond validation and pure derivations.
They are expressed with Pydantic so that the same types validate API payloads,
persist cleanly, and drive the engine — a single source of truth.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from distillery.domain.enums import (
    DatasetFormat,
    DistillationStrategy,
    ModelTask,
    TeacherType,
)


class _Frozen(BaseModel):
    """Base for immutable, value-equal models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelSpec(_Frozen):
    """Identifies and parameterises a teacher or student transformer model."""

    name_or_path: str = Field(..., min_length=1, description="HF id or local path.")
    task: ModelTask = ModelTask.SEQUENCE_CLASSIFICATION
    num_labels: int = Field(default=2, ge=1, le=100_000)
    max_seq_length: int = Field(default=128, ge=8, le=8192)
    revision: str | None = Field(default=None, description="Pinned model revision/commit.")
    #: SECURITY: executing arbitrary remote code is disabled by default.
    trust_remote_code: bool = False
    dtype: str = Field(default="float32", pattern="^(float32|float16|bfloat16)$")
    #: Build randomly-initialised weights from config only (used in tests/CI).
    config_only: bool = False

    @property
    def short_name(self) -> str:
        return self.name_or_path.rstrip("/").split("/")[-1]


class DatasetSpec(_Frozen):
    """Describes the training/evaluation corpus."""

    format: DatasetFormat
    reference: str | None = Field(
        default=None, description="HF dataset id, file path, or URL (per format)."
    )
    text_column: str = "text"
    label_column: str = "label"
    train_split: str = "train"
    eval_split: str | None = "validation"
    label_names: list[str] = Field(default_factory=list)
    max_train_samples: int | None = Field(default=None, ge=1)
    max_eval_samples: int | None = Field(default=None, ge=1)
    #: Rows for the INLINE format: ``[{"text": ..., "label": ...}, ...]``.
    inline_rows: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_source(self) -> DatasetSpec:
        if self.format is DatasetFormat.INLINE:
            if not self.inline_rows:
                raise ValueError("INLINE datasets require non-empty 'inline_rows'.")
        elif not self.reference:
            raise ValueError(f"{self.format.value} datasets require a 'reference'.")
        return self


class TrainingConfig(_Frozen):
    """Optimisation hyper-parameters for the student training loop."""

    epochs: int = Field(default=3, ge=1, le=1000)
    train_batch_size: int = Field(default=16, ge=1, le=4096)
    eval_batch_size: int = Field(default=32, ge=1, le=4096)
    learning_rate: float = Field(default=5e-5, gt=0, le=1.0)
    weight_decay: float = Field(default=0.01, ge=0, le=1.0)
    warmup_ratio: float = Field(default=0.1, ge=0, le=1.0)
    max_grad_norm: float = Field(default=1.0, ge=0)
    gradient_accumulation_steps: int = Field(default=1, ge=1, le=1024)
    seed: int = Field(default=42, ge=0)
    early_stopping_patience: int | None = Field(default=None, ge=1)
    max_steps: int | None = Field(default=None, ge=1, description="Overrides epochs if set.")


class KDHyperParams(_Frozen):
    """Knowledge-distillation loss hyper-parameters."""

    #: Softmax temperature for soft-target matching (Hinton et al., 2015).
    temperature: float = Field(default=2.0, gt=0.0, le=100.0)
    #: Weight of the soft-target (KD) term; ``1 - alpha`` weights hard CE.
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Weight of the optional intermediate feature-matching term.
    feature_loss_weight: float = Field(default=0.0, ge=0.0, le=100.0)
    #: Map of student layer index -> teacher layer index for feature KD.
    feature_layer_map: dict[int, int] = Field(default_factory=dict)


class LLMTeacherConfig(_Frozen):
    """Configuration for the LLM-as-teacher data-distillation strategy."""

    model: str = "claude-sonnet-4-6"
    task_description: str = Field(..., min_length=1)
    label_names: list[str] = Field(..., min_length=1)
    num_samples: int = Field(default=200, ge=1, le=1_000_000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    #: Optional seed examples to anchor synthetic generation (few-shot).
    seed_examples: list[dict[str, Any]] = Field(default_factory=list)
    #: When true, the LLM *labels* the provided dataset instead of generating one.
    label_existing: bool = False


class DistillationConfig(_Frozen):
    """The complete, validated specification of a distillation job."""

    strategy: DistillationStrategy
    teacher_type: TeacherType
    student: ModelSpec
    dataset: DatasetSpec
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    kd: KDHyperParams = Field(default_factory=KDHyperParams)
    teacher: ModelSpec | None = None
    llm: LLMTeacherConfig | None = None
    device: str = Field(default="auto", pattern="^(auto|cpu|cuda|mps)$")

    @model_validator(mode="after")
    def _validate_strategy_consistency(self) -> DistillationConfig:
        if self.strategy is DistillationStrategy.LLM_TEACHER:
            if self.teacher_type is not TeacherType.LLM:
                raise ValueError("LLM_TEACHER strategy requires teacher_type=LLM.")
            if self.llm is None:
                raise ValueError("LLM_TEACHER strategy requires an 'llm' configuration.")
            if self.student.num_labels != len(self.llm.label_names):
                raise ValueError("student.num_labels must equal len(llm.label_names).")
        else:
            if self.teacher_type is not TeacherType.HUGGINGFACE:
                raise ValueError(
                    f"{self.strategy.value} strategy requires teacher_type=HUGGINGFACE."
                )
            if self.teacher is None:
                raise ValueError(f"{self.strategy.value} strategy requires a 'teacher' ModelSpec.")
            if self.teacher.num_labels != self.student.num_labels:
                raise ValueError("Teacher and student must share num_labels for logit matching.")

        if self.strategy is DistillationStrategy.FEATURE_BASED and self.kd.feature_loss_weight <= 0:
            raise ValueError("FEATURE_BASED strategy requires kd.feature_loss_weight > 0.")
        return self


class JobProgress(_Frozen):
    """A point-in-time snapshot of training progress."""

    current_epoch: int = Field(default=0, ge=0)
    total_epochs: int = Field(default=0, ge=0)
    current_step: int = Field(default=0, ge=0)
    total_steps: int = Field(default=0, ge=0)
    message: str = ""

    @property
    def percent(self) -> float:
        if self.total_steps <= 0:
            return 0.0
        return round(min(100.0, 100.0 * self.current_step / self.total_steps), 2)


class ResourceUsage(_Frozen):
    """Resources consumed by a job run."""

    duration_seconds: float = Field(default=0.0, ge=0.0)
    peak_memory_mb: float = Field(default=0.0, ge=0.0)
    device: str = "cpu"
    teacher_tokens: int = Field(default=0, ge=0)


class CompressionStats(_Frozen):
    """Student-vs-teacher size comparison."""

    teacher_params: int = Field(default=0, ge=0)
    student_params: int = Field(default=0, ge=0)

    @property
    def compression_ratio(self) -> float:
        """How many times smaller the student is (teacher/student params)."""
        if self.student_params <= 0:
            return 0.0
        return round(self.teacher_params / self.student_params, 4)

    @property
    def size_reduction_percent(self) -> float:
        if self.teacher_params <= 0:
            return 0.0
        return round(100.0 * (1 - self.student_params / self.teacher_params), 2)


class EvaluationReport(_Frozen):
    """The outcome of evaluating a distilled student."""

    student_metrics: dict[str, float] = Field(default_factory=dict)
    teacher_metrics: dict[str, float] = Field(default_factory=dict)
    #: Fraction of examples where student and teacher predict the same label.
    teacher_agreement: float = Field(default=0.0, ge=0.0, le=1.0)
    compression: CompressionStats = Field(default_factory=CompressionStats)
    #: Mean single-example inference latency in milliseconds.
    student_latency_ms: float = Field(default=0.0, ge=0.0)
    teacher_latency_ms: float = Field(default=0.0, ge=0.0)

    @property
    def primary_metric(self) -> float:
        """A convenient headline score (accuracy if present, else first metric)."""
        if "accuracy" in self.student_metrics:
            return self.student_metrics["accuracy"]
        return next(iter(self.student_metrics.values()), 0.0)

    @property
    def retention(self) -> float:
        """Fraction of the teacher's accuracy retained by the student."""
        t = self.teacher_metrics.get("accuracy")
        s = self.student_metrics.get("accuracy")
        if not t or s is None or math.isclose(t, 0.0):
            return 0.0
        return round(s / t, 4)
