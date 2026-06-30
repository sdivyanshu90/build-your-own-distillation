"""Supervised strategy used by the LLM-teacher pipeline.

The LLM-teacher pipeline distils knowledge *into data*: a large language model
generates or labels a corpus (see :mod:`distillery.teachers.llm`), after which
the student is trained with ordinary supervised cross-entropy. That training
phase needs no in-memory teacher model, so this strategy sets
``requires_teacher = False`` and optimises the standard hard-label loss.
"""

from __future__ import annotations

import torch
from torch.nn import functional as F  # noqa: N812

from distillery.core.models import ModelBundle
from distillery.core.strategies.base import DistillationStrategy
from distillery.domain.exceptions import TrainingError


class SupervisedStrategy(DistillationStrategy):
    """Plain cross-entropy fine-tuning (no teacher model at train time)."""

    requires_teacher = False

    def __init__(self, label_smoothing: float = 0.0) -> None:
        if not 0.0 <= label_smoothing < 1.0:
            raise ValueError("label_smoothing must be in [0, 1)")
        self._label_smoothing = label_smoothing

    def compute_loss(
        self,
        batch: dict[str, torch.Tensor],
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        labels = batch.get("labels")
        if labels is None:
            raise TrainingError("SupervisedStrategy requires labels")

        student_out = student.model(
            input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]
        )
        loss = F.cross_entropy(student_out.logits, labels, label_smoothing=self._label_smoothing)
        return loss, {"loss": float(loss.detach()), "hard_loss": float(loss.detach())}
