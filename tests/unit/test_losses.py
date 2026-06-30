"""Unit tests for the distillation loss functions."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from distillery.core.losses import (  # noqa: E402
    FeatureDistillationLoss,
    ResponseDistillationLoss,
    soft_target_kl,
)

pytestmark = [pytest.mark.unit, pytest.mark.ml]


def test_soft_target_kl_zero_for_identical_logits() -> None:
    logits = torch.randn(4, 3)
    kl = soft_target_kl(logits, logits.clone(), temperature=2.0)
    assert kl.item() == pytest.approx(0.0, abs=1e-6)


def test_soft_target_kl_positive_for_different_logits() -> None:
    student = torch.zeros(2, 3)
    teacher = torch.tensor([[10.0, 0.0, 0.0], [0.0, 10.0, 0.0]])
    assert soft_target_kl(student, teacher, temperature=1.0).item() > 0


def test_soft_target_kl_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError):
        soft_target_kl(torch.randn(2, 2), torch.randn(2, 2), temperature=0.0)


def test_response_loss_pure_distillation_ignores_labels() -> None:
    loss_fn = ResponseDistillationLoss(temperature=2.0, alpha=1.0)
    student = torch.randn(4, 3, requires_grad=True)
    teacher = torch.randn(4, 3)
    labels = torch.tensor([0, 1, 2, 0])
    total, comp = loss_fn(student, teacher, labels)
    assert comp["hard_loss"] == 0.0
    assert comp["soft_loss"] > 0
    total.backward()
    assert student.grad is not None


def test_response_loss_pure_supervised() -> None:
    loss_fn = ResponseDistillationLoss(temperature=1.0, alpha=0.0)
    student = torch.randn(4, 3)
    teacher = torch.randn(4, 3)
    labels = torch.tensor([0, 1, 2, 0])
    total, comp = loss_fn(student, teacher, labels)
    assert comp["soft_loss"] >= 0
    assert total.item() == pytest.approx(comp["hard_loss"], abs=1e-5)


def test_response_loss_blend_and_components() -> None:
    loss_fn = ResponseDistillationLoss(temperature=2.0, alpha=0.5)
    student = torch.randn(8, 4)
    teacher = torch.randn(8, 4)
    labels = torch.randint(0, 4, (8,))
    total, comp = loss_fn(student, teacher, labels)
    expected = 0.5 * comp["soft_loss"] + 0.5 * comp["hard_loss"]
    assert total.item() == pytest.approx(expected, rel=1e-4)
    assert comp["loss"] == pytest.approx(total.item(), rel=1e-5)


@pytest.mark.parametrize("bad", [{"alpha": 1.1}, {"alpha": -0.1}, {"temperature": 0.0}])
def test_response_loss_invalid_params(bad: dict) -> None:
    with pytest.raises(ValueError):
        ResponseDistillationLoss(**bad)


def test_feature_loss_identity_when_sizes_match() -> None:
    loss_fn = FeatureDistillationLoss({1: 1}, student_hidden_size=8, teacher_hidden_size=8)
    h = torch.randn(2, 5, 8)
    student_hidden = (torch.zeros(2, 5, 8), h)
    teacher_hidden = (torch.zeros(2, 5, 8), h.clone())
    loss, comp = loss_fn(student_hidden, teacher_hidden)
    assert loss.item() == pytest.approx(0.0, abs=1e-6)
    assert "feature_loss" in comp


def test_feature_loss_projection_when_sizes_differ() -> None:
    loss_fn = FeatureDistillationLoss({1: 1}, student_hidden_size=4, teacher_hidden_size=8)
    student_hidden = (torch.randn(2, 3, 4), torch.randn(2, 3, 4))
    teacher_hidden = (torch.randn(2, 3, 8), torch.randn(2, 3, 8))
    loss, _ = loss_fn(student_hidden, teacher_hidden)
    assert torch.isfinite(loss)
    # Projection parameters are trainable.
    assert any(p.requires_grad for p in loss_fn.parameters())


def test_feature_loss_respects_attention_mask() -> None:
    loss_fn = FeatureDistillationLoss({1: 1}, student_hidden_size=4, teacher_hidden_size=4)
    student = torch.randn(2, 4, 4)
    teacher = student.clone()
    teacher[:, 2:, :] += 100.0  # huge diff only on padded positions
    mask = torch.tensor([[1, 1, 0, 0], [1, 1, 0, 0]])
    loss, _ = loss_fn(
        (torch.zeros_like(student), student), (torch.zeros_like(teacher), teacher), mask
    )
    assert loss.item() == pytest.approx(0.0, abs=1e-5)


def test_feature_loss_empty_map_rejected() -> None:
    with pytest.raises(ValueError):
        FeatureDistillationLoss({}, 4, 4)


def test_feature_loss_index_out_of_range() -> None:
    loss_fn = FeatureDistillationLoss({5: 1}, 4, 4)
    with pytest.raises(IndexError):
        loss_fn((torch.randn(1, 2, 4),), (torch.randn(1, 2, 4), torch.randn(1, 2, 4)))
