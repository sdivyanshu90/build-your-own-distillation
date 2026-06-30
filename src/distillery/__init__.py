"""Distillery — a production-grade NLP model distillation platform.

Distillery distills large "teacher" transformer models into small, fast
"student" models using three complementary strategies:

* **Response-based KD** — match the teacher's softened output distribution
  (Hinton et al., 2015) combined with the ground-truth cross-entropy loss.
* **Feature-based KD** — additionally align intermediate hidden states.
* **LLM-teacher distillation** — use a large language model (e.g. Claude) to
  synthesise or label a training corpus, then fine-tune the student on it.

The package is organised using Clean Architecture:

``distillery.domain``
    Pure business entities, value objects and ports (no framework imports).
``distillery.application``
    Use-case orchestration services that depend only on domain ports.
``distillery.core``
    The distillation engine (losses, strategies, trainer, evaluation).
``distillery.teachers``
    Teacher model adapters (HuggingFace and LLM providers).
``distillery.infrastructure``
    Concrete adapters: database, storage, queue, observability, security.
``distillery.api``
    FastAPI presentation layer.
``distillery.cli``
    Typer command-line interface.

See ``docs/architecture/overview.md`` for the full picture.
"""

from __future__ import annotations

from distillery.version import __version__

__all__ = ["__version__"]
