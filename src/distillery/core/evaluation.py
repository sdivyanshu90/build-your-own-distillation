"""Student evaluation: quality, fidelity, latency and compression.

Produces a :class:`~distillery.domain.value_objects.EvaluationReport` covering:

* **Quality** — accuracy / macro precision / recall / F1 against ground truth.
* **Fidelity** — fraction of examples where the student agrees with the teacher
  (the metric distillation is actually optimising).
* **Latency** — mean single-example inference time for student and teacher.
* **Compression** — parameter counts and reduction ratio.
"""

from __future__ import annotations

import time

import torch
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)
from torch.utils.data import DataLoader

from distillery.core.models import ModelBundle, count_parameters
from distillery.domain.value_objects import CompressionStats, EvaluationReport


@torch.no_grad()
def _collect_logits(
    model_bundle: ModelBundle, loader: DataLoader, device: torch.device
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return ``(logits, labels)`` over the whole loader."""
    model_bundle.model.to(device).eval()
    all_logits: list[torch.Tensor] = []
    all_labels: list[torch.Tensor] = []
    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        out = model_bundle.model(input_ids=input_ids, attention_mask=attention_mask)
        all_logits.append(out.logits.detach().cpu())
        all_labels.append(batch["labels"].cpu())
    return torch.cat(all_logits), torch.cat(all_labels)


def compute_classification_metrics(
    predictions: torch.Tensor, labels: torch.Tensor
) -> dict[str, float]:
    """Accuracy and macro-averaged precision/recall/F1."""
    y_pred = predictions.numpy()
    y_true = labels.numpy()
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
    }


@torch.no_grad()
def student_accuracy(student: ModelBundle, loader: DataLoader, device: torch.device) -> float:
    """Cheap accuracy probe used for early-stopping between epochs."""
    logits, labels = _collect_logits(student, loader, device)
    return float(accuracy_score(labels.numpy(), logits.argmax(dim=-1).numpy()))


@torch.no_grad()
def measure_latency_ms(
    model_bundle: ModelBundle,
    loader: DataLoader,
    device: torch.device,
    *,
    warmup: int = 2,
    iterations: int = 10,
) -> float:
    """Mean single-example inference latency in milliseconds."""
    model_bundle.model.to(device).eval()
    batch = next(iter(loader))
    input_ids = batch["input_ids"].to(device)
    attention_mask = batch["attention_mask"].to(device)
    batch_size = int(input_ids.shape[0])

    for _ in range(warmup):
        model_bundle.model(input_ids=input_ids, attention_mask=attention_mask)
    if device.type == "cuda":
        torch.cuda.synchronize()

    start = time.perf_counter()
    for _ in range(iterations):
        model_bundle.model(input_ids=input_ids, attention_mask=attention_mask)
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    per_example_seconds = elapsed / (iterations * max(1, batch_size))
    return round(per_example_seconds * 1000.0, 4)


def evaluate(
    student: ModelBundle,
    eval_loader: DataLoader,
    device: torch.device,
    *,
    teacher: ModelBundle | None = None,
    measure_latency: bool = True,
) -> EvaluationReport:
    """Build a full :class:`EvaluationReport` for a student (vs. optional teacher)."""
    student_logits, labels = _collect_logits(student, eval_loader, device)
    student_preds = student_logits.argmax(dim=-1)
    student_metrics = compute_classification_metrics(student_preds, labels)

    teacher_metrics: dict[str, float] = {}
    agreement = 0.0
    teacher_latency = 0.0
    if teacher is not None:
        teacher_logits, _ = _collect_logits(teacher, eval_loader, device)
        teacher_preds = teacher_logits.argmax(dim=-1)
        teacher_metrics = compute_classification_metrics(teacher_preds, labels)
        agreement = float((student_preds == teacher_preds).float().mean())
        if measure_latency:
            teacher_latency = measure_latency_ms(teacher, eval_loader, device)

    student_latency = measure_latency_ms(student, eval_loader, device) if measure_latency else 0.0

    compression = CompressionStats(
        teacher_params=count_parameters(teacher.model) if teacher else 0,
        student_params=count_parameters(student.model),
    )

    return EvaluationReport(
        student_metrics=student_metrics,
        teacher_metrics=teacher_metrics,
        teacher_agreement=round(agreement, 4),
        compression=compression,
        student_latency_ms=student_latency,
        teacher_latency_ms=teacher_latency,
    )
