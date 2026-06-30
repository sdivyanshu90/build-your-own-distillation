"""LLM client abstraction.

A minimal, provider-agnostic completion interface. Keeping the surface tiny means
the dataset builder depends only on :class:`LLMClient`, so any provider (or an
in-memory fake for tests) can be substituted without touching the build logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMResponse:
    """A single completion plus token accounting."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class LLMClient(Protocol):
    """A synchronous single-turn completion client."""

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Return the model's completion for ``prompt`` under ``system``."""
        ...
