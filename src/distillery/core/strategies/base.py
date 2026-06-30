"""Strategy interface shared by all distillation algorithms.

A *strategy* encapsulates the per-batch loss computation. It is the only thing
that differs between distillation algorithms; the optimisation machinery lives in
:class:`distillery.core.trainer.DistillationTrainer`, which is strategy-agnostic.
This is the Strategy pattern and keeps the trainer closed for modification but
open for extension (OCP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import torch
from torch import nn

from distillery.core.models import ModelBundle


class DistillationStrategy(ABC):
    """Computes the training loss for a single batch.

    Subclasses may build auxiliary trainable modules (e.g. feature projection
    layers) in :meth:`setup` and expose their parameters via
    :meth:`aux_parameters` so the trainer can optimise them jointly.
    """

    #: Whether the strategy needs a teacher model bundle at train time.
    requires_teacher: ClassVar[bool] = True

    def setup(  # noqa: B027 - intentional optional no-op hook, not abstract
        self,
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> None:
        """Hook to build device-resident auxiliary modules. Default: no-op."""

    def aux_parameters(self) -> list[nn.Parameter]:
        """Extra trainable parameters to include in the optimiser. Default: none."""
        return []

    @abstractmethod
    def compute_loss(
        self,
        batch: dict[str, torch.Tensor],
        student: ModelBundle,
        teacher: ModelBundle | None,
        device: torch.device,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        """Return ``(loss, components)`` for one batch already moved to device."""
        raise NotImplementedError
