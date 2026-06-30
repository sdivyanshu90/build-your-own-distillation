"""Response-based knowledge distillation (Hinton et al., 2015)."""

from __future__ import annotations

import torch

from distillery.core.losses import ResponseDistillationLoss
from distillery.core.models import ModelBundle
from distillery.core.strategies.base import DistillationStrategy
from distillery.domain.exceptions import TrainingError
from distillery.domain.value_objects import KDHyperParams


class ResponseBasedStrategy(DistillationStrategy):
    """Match the teacher's softened logits, blended with hard-label CE."""

    requires_teacher = True

    def __init__(self, kd: KDHyperParams) -> None:
        self._loss = ResponseDistillationLoss(temperature=kd.temperature, alpha=kd.alpha)

    def compute_loss(
        self,
        batch: dict[str, torch.Tensor],
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        if teacher is None:
            raise TrainingError("ResponseBasedStrategy requires a teacher model")

        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        labels = batch.get("labels")

        student_out = student.model(input_ids=input_ids, attention_mask=attention_mask)
        with torch.no_grad():
            teacher_out = teacher.model(input_ids=input_ids, attention_mask=attention_mask)

        loss, components = self._loss(student_out.logits, teacher_out.logits, labels)
        return loss, components
