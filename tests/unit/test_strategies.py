"""Unit tests for distillation strategies and the registry."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from distillery.core.models import build_tiny_classifier
from distillery.core.strategies.feature_based import (
    FeatureBasedStrategy,
    default_layer_map,
)
from distillery.core.strategies.llm_teacher import SupervisedStrategy
from distillery.core.strategies.registry import build_strategy, register_strategy
from distillery.core.strategies.response_based import ResponseBasedStrategy
from distillery.domain.enums import DistillationStrategy
from distillery.domain.exceptions import TrainingError
from distillery.domain.value_objects import KDHyperParams

pytestmark = [pytest.mark.unit, pytest.mark.ml]


@pytest.fixture
def batch():
    tok = build_tiny_classifier().tokenizer
    enc = tok(["good movie", "bad movie"], max_length=8)
    enc["labels"] = torch.tensor([1, 0])
    return enc


def test_default_layer_map_uniform() -> None:
    mapping = default_layer_map(student_layers=2, teacher_layers=4)
    assert set(mapping) == {1, 2}
    assert all(1 <= v <= 4 for v in mapping.values())


def test_default_layer_map_rejects_zero() -> None:
    with pytest.raises(ValueError):
        default_layer_map(0, 4)


def test_response_strategy_computes_loss(batch) -> None:
    student = build_tiny_classifier(num_labels=2)
    teacher = build_tiny_classifier(num_labels=2)
    strat = ResponseBasedStrategy(KDHyperParams(temperature=2.0, alpha=0.5))
    loss, comp = strat.compute_loss(batch, student, teacher, torch.device("cpu"))
    assert torch.isfinite(loss)
    assert {"soft_loss", "hard_loss", "loss"} <= set(comp)


def test_response_strategy_requires_teacher(batch) -> None:
    strat = ResponseBasedStrategy(KDHyperParams())
    with pytest.raises(TrainingError):
        strat.compute_loss(batch, build_tiny_classifier(), None, torch.device("cpu"))


def test_feature_strategy_setup_and_loss(batch) -> None:
    student = build_tiny_classifier(num_labels=2, hidden_size=16, num_hidden_layers=2)
    teacher = build_tiny_classifier(num_labels=2, hidden_size=32, num_hidden_layers=4)
    strat = FeatureBasedStrategy(KDHyperParams(feature_loss_weight=0.5))
    strat.setup(student, teacher, torch.device("cpu"))
    assert len(strat.aux_parameters()) > 0  # projections exist (sizes differ)
    loss, comp = strat.compute_loss(batch, student, teacher, torch.device("cpu"))
    assert torch.isfinite(loss)
    assert "feature_loss" in comp


def test_feature_strategy_without_setup_errors(batch) -> None:
    strat = FeatureBasedStrategy(KDHyperParams(feature_loss_weight=0.5))
    with pytest.raises(TrainingError):
        strat.compute_loss(
            batch, build_tiny_classifier(), build_tiny_classifier(), torch.device("cpu")
        )


def test_supervised_strategy(batch) -> None:
    strat = SupervisedStrategy()
    assert strat.requires_teacher is False
    loss, comp = strat.compute_loss(
        batch, build_tiny_classifier(num_labels=2), None, torch.device("cpu")
    )
    assert torch.isfinite(loss)
    assert comp["hard_loss"] == comp["loss"]


def test_supervised_strategy_requires_labels() -> None:
    strat = SupervisedStrategy()
    tok = build_tiny_classifier().tokenizer
    enc = tok(["x"], max_length=8)
    with pytest.raises(TrainingError):
        strat.compute_loss(enc, build_tiny_classifier(), None, torch.device("cpu"))


def test_registry_builds_each_strategy() -> None:
    kd = KDHyperParams(feature_loss_weight=0.5)
    assert isinstance(
        build_strategy(DistillationStrategy.RESPONSE_BASED, kd), ResponseBasedStrategy
    )
    assert isinstance(build_strategy(DistillationStrategy.FEATURE_BASED, kd), FeatureBasedStrategy)
    assert isinstance(build_strategy(DistillationStrategy.LLM_TEACHER, kd), SupervisedStrategy)


def test_registry_extension() -> None:
    register_strategy(DistillationStrategy.RESPONSE_BASED, lambda kd: SupervisedStrategy())
    assert isinstance(
        build_strategy(DistillationStrategy.RESPONSE_BASED, KDHyperParams()), SupervisedStrategy
    )
    # restore default to avoid leaking into other tests
    register_strategy(DistillationStrategy.RESPONSE_BASED, lambda kd: ResponseBasedStrategy(kd))
