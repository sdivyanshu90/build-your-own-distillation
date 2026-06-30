"""Feature-based distillation: response KD + intermediate hidden-state alignment.

Extends :class:`ResponseBasedStrategy` with an MSE term over mapped hidden
layers (FitNets / TinyBERT style). When the student has fewer layers than the
teacher, a uniform layer map is derived automatically.
"""

from __future__ import annotations

import torch
from torch import nn

from distillery.core.losses import FeatureDistillationLoss
from distillery.core.models import ModelBundle
from distillery.core.strategies.response_based import ResponseBasedStrategy
from distillery.domain.exceptions import TrainingError
from distillery.domain.value_objects import KDHyperParams


def default_layer_map(student_layers: int, teacher_layers: int) -> dict[int, int]:
    """Uniformly map each student layer onto a teacher layer.

    Hidden-state tuples include the embedding output at index 0, so we map the
    ``student_layers`` transformer outputs (indices 1..S) onto evenly-spaced
    teacher outputs (indices 1..T).
    """
    if student_layers <= 0 or teacher_layers <= 0:
        raise ValueError("layer counts must be positive")
    mapping: dict[int, int] = {}
    for s in range(1, student_layers + 1):
        t = max(1, round(s * teacher_layers / student_layers))
        mapping[s] = min(t, teacher_layers)
    return mapping


class FeatureBasedStrategy(ResponseBasedStrategy):
    """Response KD plus weighted intermediate feature matching."""

    requires_teacher = True

    def __init__(self, kd: KDHyperParams) -> None:
        super().__init__(kd)
        self._kd = kd
        self._feature_loss: FeatureDistillationLoss | None = None

    def setup(
        self,
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> None:
        if teacher is None:
            raise TrainingError("FeatureBasedStrategy requires a teacher model")
        layer_map = self._kd.feature_layer_map or default_layer_map(
            student.num_hidden_layers, teacher.num_hidden_layers
        )
        self._feature_loss = FeatureDistillationLoss(
            layer_map=layer_map,
            student_hidden_size=student.hidden_size,
            teacher_hidden_size=teacher.hidden_size,
        ).to(device)

    def aux_parameters(self) -> list[nn.Parameter]:
        if self._feature_loss is None:
            return []
        return list(self._feature_loss.parameters())

    def compute_loss(
        self,
        batch: dict[str, torch.Tensor],
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        if teacher is None or self._feature_loss is None:
            raise TrainingError("FeatureBasedStrategy was not set up with a teacher")

        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        labels = batch.get("labels")

        student_out = student.model(
            input_ids=input_ids, attention_mask=attention_mask, output_hidden_states=True
        )
        with torch.no_grad():
            teacher_out = teacher.model(
                input_ids=input_ids, attention_mask=attention_mask, output_hidden_states=True
            )

        response_loss, components = self._loss(student_out.logits, teacher_out.logits, labels)
        feature_loss, feature_components = self._feature_loss(
            student_out.hidden_states, teacher_out.hidden_states, attention_mask
        )

        total = response_loss + self._kd.feature_loss_weight * feature_loss
        components.update(feature_components)
        components["loss"] = float(total.detach())
        return total, components
