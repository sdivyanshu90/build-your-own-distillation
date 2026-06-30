"""Strategy registry — maps a :class:`DistillationStrategy` enum to a builder.

New algorithms register a factory here and become available to the engine and
API without any change to call sites (Open/Closed Principle).
"""

from __future__ import annotations

from collections.abc import Callable

from distillery.core.strategies.base import DistillationStrategy
from distillery.core.strategies.feature_based import FeatureBasedStrategy
from distillery.core.strategies.llm_teacher import SupervisedStrategy
from distillery.core.strategies.response_based import ResponseBasedStrategy
from distillery.domain.enums import DistillationStrategy as StrategyEnum
from distillery.domain.exceptions import ValidationError
from distillery.domain.value_objects import KDHyperParams

StrategyFactory = Callable[[KDHyperParams], DistillationStrategy]

_REGISTRY: dict[StrategyEnum, StrategyFactory] = {
    StrategyEnum.RESPONSE_BASED: lambda kd: ResponseBasedStrategy(kd),
    StrategyEnum.FEATURE_BASED: lambda kd: FeatureBasedStrategy(kd),
    StrategyEnum.LLM_TEACHER: lambda _kd: SupervisedStrategy(),
}


def register_strategy(name: StrategyEnum, factory: StrategyFactory) -> None:
    """Register (or override) a strategy factory."""
    _REGISTRY[name] = factory


def build_strategy(name: StrategyEnum, kd: KDHyperParams) -> DistillationStrategy:
    """Instantiate the strategy registered under ``name``."""
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:
        raise ValidationError(f"Unknown distillation strategy: {name}") from exc
    return factory(kd)
