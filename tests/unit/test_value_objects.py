"""Unit tests for value-object validation and derived properties."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from distillery.domain.enums import DatasetFormat, DistillationStrategy, TeacherType
from distillery.domain.value_objects import (
    CompressionStats,
    DatasetSpec,
    DistillationConfig,
    EvaluationReport,
    JobProgress,
    KDHyperParams,
    LLMTeacherConfig,
    ModelSpec,
)

pytestmark = pytest.mark.unit


def test_model_spec_short_name() -> None:
    assert ModelSpec(name_or_path="org/bert-base").short_name == "bert-base"
    assert ModelSpec(name_or_path="local/path/").short_name == "path"


def test_dataset_inline_requires_rows() -> None:
    with pytest.raises(PydanticValidationError):
        DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[])


def test_dataset_hub_requires_reference() -> None:
    with pytest.raises(PydanticValidationError):
        DatasetSpec(format=DatasetFormat.HF_HUB)


def test_kd_hyperparams_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        KDHyperParams(temperature=0)
    with pytest.raises(PydanticValidationError):
        KDHyperParams(alpha=1.5)


def test_job_progress_percent() -> None:
    assert JobProgress(current_step=0, total_steps=0).percent == 0.0
    assert JobProgress(current_step=5, total_steps=10).percent == 50.0
    assert JobProgress(current_step=50, total_steps=10).percent == 100.0  # clamped


def test_compression_stats() -> None:
    stats = CompressionStats(teacher_params=1000, student_params=250)
    assert stats.compression_ratio == 4.0
    assert stats.size_reduction_percent == 75.0
    assert CompressionStats(teacher_params=0, student_params=0).compression_ratio == 0.0


def test_evaluation_report_derivations() -> None:
    report = EvaluationReport(
        student_metrics={"accuracy": 0.9, "f1_macro": 0.88},
        teacher_metrics={"accuracy": 0.95},
        teacher_agreement=0.92,
    )
    assert report.primary_metric == 0.9
    assert report.retention == round(0.9 / 0.95, 4)
    # No teacher accuracy -> retention 0
    assert EvaluationReport(student_metrics={"accuracy": 0.9}).retention == 0.0
    # No accuracy key -> first metric
    assert EvaluationReport(student_metrics={"f1": 0.5}).primary_metric == 0.5


def _base_kwargs() -> dict:
    return {
        "student": ModelSpec(name_or_path="s", num_labels=2),
        "dataset": DatasetSpec(
            format=DatasetFormat.INLINE, inline_rows=[{"text": "a", "label": 0}]
        ),
    }


def test_response_config_requires_teacher() -> None:
    with pytest.raises(PydanticValidationError, match="requires a 'teacher'"):
        DistillationConfig(
            strategy=DistillationStrategy.RESPONSE_BASED,
            teacher_type=TeacherType.HUGGINGFACE,
            **_base_kwargs(),
        )


def test_teacher_student_label_mismatch_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="num_labels"):
        DistillationConfig(
            strategy=DistillationStrategy.RESPONSE_BASED,
            teacher_type=TeacherType.HUGGINGFACE,
            teacher=ModelSpec(name_or_path="t", num_labels=3),
            **_base_kwargs(),
        )


def test_feature_strategy_requires_weight() -> None:
    with pytest.raises(PydanticValidationError, match="feature_loss_weight"):
        DistillationConfig(
            strategy=DistillationStrategy.FEATURE_BASED,
            teacher_type=TeacherType.HUGGINGFACE,
            teacher=ModelSpec(name_or_path="t", num_labels=2),
            kd=KDHyperParams(feature_loss_weight=0.0),
            **_base_kwargs(),
        )


def test_llm_strategy_validation() -> None:
    # Wrong teacher type
    with pytest.raises(PydanticValidationError, match="teacher_type=LLM"):
        DistillationConfig(
            strategy=DistillationStrategy.LLM_TEACHER,
            teacher_type=TeacherType.HUGGINGFACE,
            llm=LLMTeacherConfig(task_description="x", label_names=["a", "b"]),
            **_base_kwargs(),
        )
    # label count must match student labels
    with pytest.raises(PydanticValidationError, match="label_names"):
        DistillationConfig(
            strategy=DistillationStrategy.LLM_TEACHER,
            teacher_type=TeacherType.LLM,
            student=ModelSpec(name_or_path="s", num_labels=2),
            dataset=DatasetSpec(
                format=DatasetFormat.INLINE, inline_rows=[{"text": "a", "label": 0}]
            ),
            llm=LLMTeacherConfig(task_description="x", label_names=["only-one"]),
        )


def test_valid_llm_config() -> None:
    cfg = DistillationConfig(
        strategy=DistillationStrategy.LLM_TEACHER,
        teacher_type=TeacherType.LLM,
        student=ModelSpec(name_or_path="s", num_labels=2),
        dataset=DatasetSpec(format=DatasetFormat.INLINE, inline_rows=[{"text": "a", "label": 0}]),
        llm=LLMTeacherConfig(task_description="sentiment", label_names=["neg", "pos"]),
    )
    assert cfg.strategy is DistillationStrategy.LLM_TEACHER


def test_value_objects_are_frozen() -> None:
    spec = ModelSpec(name_or_path="x")
    with pytest.raises(PydanticValidationError):
        spec.num_labels = 5  # type: ignore[misc]
