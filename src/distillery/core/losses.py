"""Knowledge-distillation loss functions (pure PyTorch).

Two complementary objectives are implemented:

* :class:`ResponseDistillationLoss` — the classic Hinton soft-target objective:
  a temperature-scaled KL divergence between the student's and teacher's output
  distributions, blended with the ground-truth cross-entropy.
* :class:`FeatureDistillationLoss` — an intermediate hidden-state alignment
  objective (à la FitNets/TinyBERT) with learned linear projections so that
  student and teacher hidden sizes need not match.

Both modules are deterministic, side-effect free, and individually unit-tested.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F  # noqa: N812


def soft_target_kl(
    student_logits: torch.Tensor,
    teacher_logits: torch.Tensor,
    temperature: float,
) -> torch.Tensor:
    """Temperature-scaled KL divergence ``KL(teacher || student)``.

    The result is multiplied by ``T**2`` so that gradient magnitudes are
    comparable to the unscaled hard-label loss, as recommended by Hinton et al.

    Args:
        student_logits: ``[batch, num_classes]`` raw student logits.
        teacher_logits: ``[batch, num_classes]`` raw teacher logits (no grad).
        temperature: Softmax temperature ``T > 0``. Higher ``T`` softens.

    Returns:
        A scalar tensor (mean over the batch).
    """
    if temperature <= 0:
        raise ValueError("temperature must be > 0")
    t = temperature
    student_log_probs = F.log_softmax(student_logits / t, dim=-1)
    teacher_probs = F.softmax(teacher_logits / t, dim=-1)
    # batchmean matches the mathematical definition of KL over the batch.
    kl = F.kl_div(student_log_probs, teacher_probs, reduction="batchmean")
    return kl * (t * t)


class ResponseDistillationLoss(nn.Module):
    """Blend of soft-target KD and hard-label cross-entropy.

    ``loss = alpha * T^2 * KL(teacher || student) + (1 - alpha) * CE(student, y)``

    Args:
        temperature: Distillation temperature ``T``.
        alpha: Weight of the soft (KD) term in ``[0, 1]``. ``alpha=1`` is pure
            distillation; ``alpha=0`` is pure supervised fine-tuning.
    """

    def __init__(self, temperature: float = 2.0, alpha: float = 0.5) -> None:
        super().__init__()
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        if temperature <= 0:
            raise ValueError("temperature must be > 0")
        self.temperature = float(temperature)
        self.alpha = float(alpha)

    def forward(
        self,
        student_logits: torch.Tensor,
        teacher_logits: torch.Tensor,
        labels: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        """Compute the blended loss.

        Returns:
            A tuple ``(loss, components)`` where ``components`` carries the
            detached scalar values of each term for logging.
        """
        soft = soft_target_kl(student_logits, teacher_logits, self.temperature)

        if self.alpha >= 1.0 or labels is None:
            hard = torch.zeros((), device=student_logits.device, dtype=soft.dtype)
        else:
            hard = F.cross_entropy(student_logits, labels)

        total = self.alpha * soft + (1.0 - self.alpha) * hard
        components = {
            "soft_loss": float(soft.detach()),
            "hard_loss": float(hard.detach()),
            "loss": float(total.detach()),
        }
        return total, components


class FeatureDistillationLoss(nn.Module):
    """Mask-aware MSE between projected student and teacher hidden states.

    For each ``(student_layer -> teacher_layer)`` mapping, the student's hidden
    state is linearly projected into the teacher's hidden size and compared with
    MSE over non-padding tokens. Projections are learnable parameters trained
    jointly with the student.

    Args:
        layer_map: ``{student_layer_index: teacher_layer_index}``.
        student_hidden_size: Student model hidden dimension.
        teacher_hidden_size: Teacher model hidden dimension.
    """

    def __init__(
        self,
        layer_map: dict[int, int],
        student_hidden_size: int,
        teacher_hidden_size: int,
    ) -> None:
        super().__init__()
        if not layer_map:
            raise ValueError("layer_map must be non-empty for feature distillation")
        self.layer_map = dict(layer_map)
        # One projection per student layer (identity if sizes already match).
        self.projections = nn.ModuleDict(
            {
                str(s_idx): (
                    nn.Identity()
                    if student_hidden_size == teacher_hidden_size
                    else nn.Linear(student_hidden_size, teacher_hidden_size, bias=False)
                )
                for s_idx in layer_map
            }
        )

    def forward(
        self,
        student_hidden_states: tuple[torch.Tensor, ...],
        teacher_hidden_states: tuple[torch.Tensor, ...],
        attention_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        """Compute the aggregate feature-matching loss across mapped layers."""
        device = student_hidden_states[0].device
        total = torch.zeros((), device=device)

        if attention_mask is not None:
            mask = attention_mask.unsqueeze(-1).to(student_hidden_states[0].dtype)
        else:
            mask = None

        for s_idx, t_idx in self.layer_map.items():
            self._check_index(s_idx, len(student_hidden_states), "student")
            self._check_index(t_idx, len(teacher_hidden_states), "teacher")
            student_h = self.projections[str(s_idx)](student_hidden_states[s_idx])
            teacher_h = teacher_hidden_states[t_idx]

            if mask is not None:
                diff = (student_h - teacher_h) * mask
                denom = mask.sum().clamp_min(1.0) * student_h.shape[-1]
                total = total + diff.pow(2).sum() / denom
            else:
                total = total + F.mse_loss(student_h, teacher_h)

        total = total / len(self.layer_map)
        return total, {"feature_loss": float(total.detach())}

    @staticmethod
    def _check_index(idx: int, length: int, side: str) -> None:
        if not -length <= idx < length:
            raise IndexError(f"{side} layer index {idx} out of range for {length} hidden states")
