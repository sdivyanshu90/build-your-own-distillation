"""End-to-end engine tests for all three distillation strategies (CPU, tiny)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")

from distillery.core.engine import DefaultDistillationEngine
from distillery.domain.enums import (
    ArtifactType,
    DatasetFormat,
    DistillationStrategy,
    TeacherType,
)
from distillery.domain.value_objects import (
    DatasetSpec,
    DistillationConfig,
    KDHyperParams,
    LLMTeacherConfig,
    ModelSpec,
    TrainingConfig,
)

pytestmark = [pytest.mark.integration, pytest.mark.ml]

_ROWS = [{"text": f"great wonderful {i}", "label": 1} for i in range(8)] + [
    {"text": f"awful terrible {i}", "label": 0} for i in range(8)
]


def _tiny(num_labels: int = 2) -> ModelSpec:
    return ModelSpec(name_or_path="m", num_labels=num_labels, config_only=True, max_seq_length=16)


def _dataset() -> DatasetSpec:
    return DatasetSpec(format=DatasetFormat.INLINE, inline_rows=_ROWS, label_names=["neg", "pos"])


def _training() -> TrainingConfig:
    return TrainingConfig(epochs=1, train_batch_size=4, warmup_ratio=0.0)


def test_response_based_engine(tmp_path: Path) -> None:
    cfg = DistillationConfig(
        strategy=DistillationStrategy.RESPONSE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=_tiny(),
        student=_tiny(),
        dataset=_dataset(),
        training=_training(),
        kd=KDHyperParams(temperature=2.0, alpha=0.5),
        device="cpu",
    )
    result = DefaultDistillationEngine().run(cfg, work_dir=tmp_path)
    assert 0.0 <= result.evaluation.primary_metric <= 1.0
    assert result.evaluation.compression.student_params > 0
    types = {a.type for a in result.artifacts}
    assert ArtifactType.STUDENT_MODEL in types
    assert ArtifactType.EVALUATION_REPORT in types
    # report file is valid JSON
    report = next(a for a in result.artifacts if a.type is ArtifactType.EVALUATION_REPORT)
    json.loads(report.local_path.read_text())


def test_feature_based_engine(tmp_path: Path) -> None:
    cfg = DistillationConfig(
        strategy=DistillationStrategy.FEATURE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=_tiny(),
        student=_tiny(),
        dataset=_dataset(),
        training=_training(),
        kd=KDHyperParams(temperature=2.0, alpha=0.5, feature_loss_weight=0.5),
        device="cpu",
    )
    result = DefaultDistillationEngine().run(cfg, work_dir=tmp_path)
    assert result.resource_usage.duration_seconds >= 0


def test_engine_with_early_stopping(tmp_path: Path) -> None:
    cfg = DistillationConfig(
        strategy=DistillationStrategy.RESPONSE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=_tiny(),
        student=_tiny(),
        dataset=_dataset(),  # inline datasets provide an eval split
        training=TrainingConfig(
            epochs=3, train_batch_size=4, warmup_ratio=0.0, early_stopping_patience=1
        ),
        kd=KDHyperParams(temperature=2.0, alpha=0.5),
        device="cpu",
    )
    result = DefaultDistillationEngine().run(cfg, work_dir=tmp_path)
    assert result.evaluation is not None


def test_llm_teacher_engine_with_fake_builder(tmp_path: Path) -> None:
    def fake_builder(llm_cfg, ds_spec):
        rows = [{"text": f"pos {i}", "label": "pos"} for i in range(6)] + [
            {"text": f"neg {i}", "label": "neg"} for i in range(6)
        ]
        return rows, 4242

    cfg = DistillationConfig(
        strategy=DistillationStrategy.LLM_TEACHER,
        teacher_type=TeacherType.LLM,
        student=_tiny(),
        dataset=DatasetSpec(
            format=DatasetFormat.INLINE,
            inline_rows=[{"text": "seed", "label": "pos"}],
            label_names=["neg", "pos"],
        ),
        training=_training(),
        llm=LLMTeacherConfig(
            task_description="sentiment", label_names=["neg", "pos"], num_samples=12
        ),
        device="cpu",
    )
    result = DefaultDistillationEngine(llm_dataset_builder=fake_builder).run(cfg, work_dir=tmp_path)
    assert result.resource_usage.teacher_tokens == 4242
    assert ArtifactType.SYNTHETIC_DATASET in {a.type for a in result.artifacts}
