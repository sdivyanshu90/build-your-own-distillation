"""Unit tests for the training loop (learning, progress, early stopping)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from distillery.core.data import build_datasets, make_dataloader  # noqa: E402
from distillery.core.evaluation import student_accuracy  # noqa: E402
from distillery.core.models import build_tiny_classifier  # noqa: E402
from distillery.core.strategies.llm_teacher import SupervisedStrategy  # noqa: E402
from distillery.core.strategies.response_based import ResponseBasedStrategy  # noqa: E402
from distillery.core.trainer import DistillationTrainer, set_seed  # noqa: E402
from distillery.domain.enums import DatasetFormat  # noqa: E402
from distillery.domain.exceptions import TrainingError  # noqa: E402
from distillery.domain.value_objects import (  # noqa: E402
    DatasetSpec,
    JobProgress,
    KDHyperParams,
    TrainingConfig,
)

pytestmark = [pytest.mark.unit, pytest.mark.ml]
DEVICE = torch.device("cpu")


def _separable_loader(student, batch_size=4):
    rows = [{"text": "pos pos pos great", "label": 1} for _ in range(12)] + [
        {"text": "neg neg neg awful", "label": 0} for _ in range(12)
    ]
    spec = DatasetSpec(format=DatasetFormat.INLINE, inline_rows=rows, label_names=["neg", "pos"])
    bundle = build_datasets(spec, student.tokenizer, max_seq_length=8)
    return bundle.train, make_dataloader(bundle.train, batch_size=batch_size, shuffle=True, seed=0)


def test_supervised_training_learns_separable_task() -> None:
    set_seed(0)
    student = build_tiny_classifier(num_labels=2, hidden_size=32)
    dataset, loader = _separable_loader(student)
    cfg = TrainingConfig(epochs=20, train_batch_size=4, learning_rate=1e-2, warmup_ratio=0.0)
    trainer = DistillationTrainer(SupervisedStrategy(), cfg, DEVICE)
    result = trainer.train(student, None, loader)
    assert result.global_step > 0
    eval_loader = make_dataloader(dataset, batch_size=8, shuffle=False)
    assert student_accuracy(student, eval_loader, DEVICE) >= 0.75


def test_progress_callback_invoked() -> None:
    student = build_tiny_classifier(num_labels=2)
    _, loader = _separable_loader(student)
    seen: list[JobProgress] = []
    cfg = TrainingConfig(epochs=1, train_batch_size=4, warmup_ratio=0.0)
    trainer = DistillationTrainer(SupervisedStrategy(), cfg, DEVICE, on_progress=seen.append)
    trainer.train(student, None, loader)
    assert seen
    assert seen[-1].percent <= 100.0


def test_empty_loader_raises() -> None:
    from torch.utils.data import DataLoader

    from distillery.core.data import TokenizedDataset

    empty = TokenizedDataset(
        torch.zeros(0, 4, dtype=torch.long),
        torch.zeros(0, 4, dtype=torch.long),
        torch.zeros(0, dtype=torch.long),
    )
    loader = DataLoader(empty, batch_size=2)
    trainer = DistillationTrainer(SupervisedStrategy(), TrainingConfig(epochs=1), DEVICE)
    with pytest.raises(TrainingError):
        trainer.train(build_tiny_classifier(), None, loader)


def test_requires_teacher_enforced() -> None:
    student = build_tiny_classifier(num_labels=2)
    _, loader = _separable_loader(student)
    trainer = DistillationTrainer(
        ResponseBasedStrategy(KDHyperParams()), TrainingConfig(epochs=1), DEVICE
    )
    with pytest.raises(TrainingError):
        trainer.train(student, None, loader)


def test_early_stopping_triggers() -> None:
    student = build_tiny_classifier(num_labels=2)
    _, loader = _separable_loader(student)
    cfg = TrainingConfig(epochs=6, train_batch_size=4, warmup_ratio=0.0, early_stopping_patience=1)
    trainer = DistillationTrainer(SupervisedStrategy(), cfg, DEVICE)

    metrics = iter([0.9, 0.5, 0.4, 0.3, 0.2, 0.1])  # strictly decreasing after first

    def epoch_eval(_epoch: int) -> float:
        return next(metrics)

    result = trainer.train(student, None, loader, epoch_eval=epoch_eval)
    assert result.epochs_run < cfg.epochs
    assert result.best_metric == 0.9


def test_max_steps_caps_training() -> None:
    student = build_tiny_classifier(num_labels=2)
    _, loader = _separable_loader(student, batch_size=2)
    cfg = TrainingConfig(epochs=10, train_batch_size=2, warmup_ratio=0.0, max_steps=3)
    trainer = DistillationTrainer(SupervisedStrategy(), cfg, DEVICE)
    result = trainer.train(student, None, loader)
    assert result.global_step == 3
