"""The distillation engine — losses, data, models, strategies, training, eval.

This package contains the pure-ML core. It imports ``torch``/``transformers``
and therefore must only be imported by the worker/CLI execution paths, never by
the (lightweight) API request path. The public entry point is
:class:`distillery.core.engine.DefaultDistillationEngine`, which implements the
:class:`distillery.domain.ports.DistillationEngine` port.
"""

from __future__ import annotations

__all__ = ["build_engine"]


def build_engine() -> object:
    """Lazily construct the default engine (keeps torch import out of import time)."""
    from distillery.core.engine import DefaultDistillationEngine

    return DefaultDistillationEngine()
