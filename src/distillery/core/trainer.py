"""The strategy-agnostic training loop.

:class:`DistillationTrainer` owns optimisation concerns common to every
strategy: optimiser/scheduler construction, gradient accumulation and clipping,
deterministic seeding, progress reporting and optional early stopping. The
loss itself is delegated to a :class:`DistillationStrategy`.
"""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from distillery.core.models import ModelBundle
from distillery.core.strategies.base import DistillationStrategy
from distillery.domain.exceptions import TrainingError
from distillery.domain.value_objects import JobProgress, TrainingConfig

logger = logging.getLogger(__name__)

ProgressFn = Callable[[JobProgress], None]
EpochEvalFn = Callable[[int], float]


def set_seed(seed: int) -> None:
    """Seed Python, NumPy and PyTorch RNGs for reproducible runs."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


@dataclass
class TrainingResult:
    """Outcome of a training run."""

    global_step: int
    epochs_run: int
    history: list[dict[str, float]] = field(default_factory=list)
    best_metric: float | None = None


class DistillationTrainer:
    """Drives optimisation of a student model under a given strategy."""

    def __init__(
        self,
        strategy: DistillationStrategy,
        config: TrainingConfig,
        device: torch.device,
        *,
        gradient_clip_norm: float = 1.0,
        on_progress: ProgressFn | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config
        self.device = device
        self.gradient_clip_norm = gradient_clip_norm
        self.on_progress = on_progress

    def _total_optimizer_steps(self, num_batches: int) -> int:
        per_epoch = max(1, math.ceil(num_batches / self.config.gradient_accumulation_steps))
        if self.config.max_steps:
            return self.config.max_steps
        return per_epoch * self.config.epochs

    def train(
        self,
        student: ModelBundle,
        teacher: ModelBundle | None,
        train_loader: DataLoader,
        *,
        epoch_eval: EpochEvalFn | None = None,
    ) -> TrainingResult:
        """Train ``student`` and return a :class:`TrainingResult`.

        Args:
            student: the student bundle to optimise (modified in place).
            teacher: the teacher bundle, or ``None`` for teacher-free strategies.
            train_loader: batches yielding ``input_ids/attention_mask/labels``.
            epoch_eval: optional callback returning a monitored metric (higher is
                better) at the end of each epoch; enables early stopping when
                ``config.early_stopping_patience`` is set.
        """
        if self.strategy.requires_teacher and teacher is None:
            raise TrainingError("Strategy requires a teacher but none was provided")
        if len(train_loader) == 0:
            raise TrainingError("Training dataloader is empty")

        set_seed(self.config.seed)
        self.strategy.setup(student, teacher, self.device)

        student.model.to(self.device).train()
        if teacher is not None:
            teacher.model.to(self.device).eval()
            for param in teacher.model.parameters():
                param.requires_grad_(False)

        total_steps = self._total_optimizer_steps(len(train_loader))
        optimizer = self._build_optimizer(student)
        scheduler = self._build_scheduler(optimizer, total_steps)

        result = TrainingResult(global_step=0, epochs_run=0)
        best_metric = -math.inf
        best_state: dict[str, torch.Tensor] | None = None
        epochs_without_improvement = 0
        accum = self.config.gradient_accumulation_steps

        for epoch in range(self.config.epochs):
            student.model.train()
            optimizer.zero_grad(set_to_none=True)
            running: dict[str, float] = {}

            for batch_idx, raw_batch in enumerate(train_loader):
                batch = {k: v.to(self.device) for k, v in raw_batch.items()}
                loss, components = self.strategy.compute_loss(batch, student, teacher, self.device)
                (loss / accum).backward()
                running = components

                is_step = (batch_idx + 1) % accum == 0 or (batch_idx + 1) == len(train_loader)
                if is_step:
                    self._clip_grads(student, optimizer)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    result.global_step += 1
                    self._report(epoch, result.global_step, total_steps, components)
                    if self.config.max_steps and result.global_step >= self.config.max_steps:
                        break

            result.history.append({"epoch": float(epoch + 1), **running})
            result.epochs_run = epoch + 1

            if epoch_eval is not None:
                metric = epoch_eval(epoch)
                result.best_metric = max(metric, best_metric if best_metric > -math.inf else metric)
                if metric > best_metric:
                    best_metric = metric
                    epochs_without_improvement = 0
                    if self.config.early_stopping_patience:
                        best_state = deepcopy(student.model.state_dict())
                else:
                    epochs_without_improvement += 1
                    if (
                        self.config.early_stopping_patience
                        and epochs_without_improvement >= self.config.early_stopping_patience
                    ):
                        logger.info("Early stopping at epoch %d", epoch + 1)
                        break

            if self.config.max_steps and result.global_step >= self.config.max_steps:
                break

        if best_state is not None:
            student.model.load_state_dict(best_state)
            result.best_metric = best_metric

        return result

    # -- helpers -----------------------------------------------------------
    def _build_optimizer(self, student: ModelBundle) -> AdamW:
        decay, no_decay = [], []
        for name, param in student.model.named_parameters():
            if not param.requires_grad:
                continue
            if param.ndim <= 1 or name.endswith(".bias") or "norm" in name.lower():
                no_decay.append(param)
            else:
                decay.append(param)
        groups = [
            {"params": decay, "weight_decay": self.config.weight_decay},
            {"params": no_decay, "weight_decay": 0.0},
        ]
        aux = self.strategy.aux_parameters()
        if aux:
            groups.append({"params": aux, "weight_decay": self.config.weight_decay})
        return AdamW(groups, lr=self.config.learning_rate)

    def _build_scheduler(self, optimizer: AdamW, total_steps: int) -> Any:
        from transformers import get_linear_schedule_with_warmup

        warmup_steps = int(self.config.warmup_ratio * total_steps)
        return get_linear_schedule_with_warmup(
            optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
        )

    def _clip_grads(self, student: ModelBundle, optimizer: AdamW) -> None:
        if self.gradient_clip_norm and self.gradient_clip_norm > 0:
            params = [p for group in optimizer.param_groups for p in group["params"]]
            torch.nn.utils.clip_grad_norm_(params, self.gradient_clip_norm)

    def _report(self, epoch: int, step: int, total: int, components: dict[str, float]) -> None:
        if self.on_progress is None:
            return
        self.on_progress(
            JobProgress(
                current_epoch=epoch + 1,
                total_epochs=self.config.epochs,
                current_step=step,
                total_steps=total,
                message=f"loss={components.get('loss', 0.0):.4f}",
            )
        )
