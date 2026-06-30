"""Distillation strategies and their registry."""

from __future__ import annotations

from distillery.core.strategies.base import DistillationStrategy
from distillery.core.strategies.feature_based import FeatureBasedStrategy
from distillery.core.strategies.llm_teacher import SupervisedStrategy
from distillery.core.strategies.registry import build_strategy, register_strategy
from distillery.core.strategies.response_based import ResponseBasedStrategy

__all__ = [
    "DistillationStrategy",
    "FeatureBasedStrategy",
    "ResponseBasedStrategy",
    "SupervisedStrategy",
    "build_strategy",
    "register_strategy",
]
