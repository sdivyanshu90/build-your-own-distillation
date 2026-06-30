"""Unit tests for evaluation metrics, fidelity, latency and compression."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from distillery.core.data import build_datasets, make_dataloader
from distillery.core.evaluation import (
    compute_classification_metrics,
    evaluate,
    measure_latency_ms,
    student_accuracy,
)
from distillery.core.models import build_tiny_classifier
from distillery.domain.enums import DatasetFormat
from distillery.domain.value_objects import DatasetSpec

pytestmark = [pytest.mark.unit, pytest.mark.ml]
DEVICE = torch.device("cpu")


def test_classification_metrics_perfect() -> None:
    preds = torch.tensor([0, 1, 0, 1])
    labels = torch.tensor([0, 1, 0, 1])
    m = compute_classification_metrics(preds, labels)
    assert m["accuracy"] == 1.0
    assert m["f1_macro"] == 1.0


def test_classification_metrics_partial() -> None:
    preds = torch.tensor([0, 0, 0, 0])
    labels = torch.tensor([0, 1, 0, 1])
    m = compute_classification_metrics(preds, labels)
    assert m["accuracy"] == 0.5
    assert 0.0 <= m["f1_macro"] <= 1.0


@pytest.fixture
def loader():
    student = build_tiny_classifier(num_labels=2, hidden_size=16, num_hidden_layers=2)
    rows = [{"text": f"x {i}", "label": i % 2} for i in range(8)]
    spec = DatasetSpec(format=DatasetFormat.INLINE, inline_rows=rows, label_names=["a", "b"])
    bundle = build_datasets(spec, student.tokenizer, max_seq_length=8)
    return student, make_dataloader(bundle.train, batch_size=4, shuffle=False)


def test_student_accuracy_in_range(loader) -> None:
    student, dl = loader
    acc = student_accuracy(student, dl, DEVICE)
    assert 0.0 <= acc <= 1.0


def test_measure_latency_positive(loader) -> None:
    student, dl = loader
    assert measure_latency_ms(student, dl, DEVICE, warmup=1, iterations=2) >= 0.0


def test_evaluate_with_teacher(loader) -> None:
    student, dl = loader
    teacher = build_tiny_classifier(num_labels=2, hidden_size=32, num_hidden_layers=2)
    report = evaluate(student, dl, DEVICE, teacher=teacher)
    assert 0.0 <= report.teacher_agreement <= 1.0
    assert "accuracy" in report.student_metrics
    assert "accuracy" in report.teacher_metrics
    assert report.compression.teacher_params > report.compression.student_params
    assert report.compression.compression_ratio > 1.0


def test_evaluate_without_teacher(loader) -> None:
    student, dl = loader
    report = evaluate(student, dl, DEVICE, teacher=None, measure_latency=False)
    assert report.teacher_metrics == {}
    assert report.teacher_agreement == 0.0
    assert report.compression.teacher_params == 0
    assert report.student_latency_ms == 0.0
