"""Anthropic-backed implementation of :class:`LLMClient`.

Wraps the official ``anthropic`` SDK with retry/backoff (via :mod:`tenacity`)
and token accounting. The SDK is imported lazily so the rest of the platform
does not require it unless an LLM-teacher job actually runs.
"""

from __future__ import annotations

import logging
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from distillery.config.settings import Settings, get_settings
from distillery.domain.exceptions import TeacherError
from distillery.teachers.llm.base import LLMResponse

logger = logging.getLogger(__name__)


class AnthropicLLMClient:
    """A synchronous Anthropic Messages API client implementing ``LLMClient``."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 120.0,
        max_retries: int = 5,
    ) -> None:
        if not api_key:
            raise TeacherError("An Anthropic API key is required for LLM-teacher jobs")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise TeacherError(
                "The 'anthropic' package is required; install distillery[llm]"
            ) from exc

        # The SDK has its own retry handling; we add an outer jittered retry too.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self._max_retries = max_retries
        self._retryable = self._resolve_retryable_errors(anthropic)

    @staticmethod
    def _resolve_retryable_errors(anthropic: Any) -> tuple[type[Exception], ...]:
        names = ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError")
        errors = tuple(getattr(anthropic, n) for n in names if hasattr(anthropic, n))
        return errors or (Exception,)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> AnthropicLLMClient:
        settings = settings or get_settings()
        return cls(
            api_key=settings.llm.anthropic_api_key.get_secret_value(),
            timeout=float(settings.llm.request_timeout_seconds),
            max_retries=settings.llm.max_retries,
        )

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        return self._complete_with_retry(
            system=system,
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _complete_with_retry(self, **kwargs: Any) -> LLMResponse:
        retryer = retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_random_exponential(multiplier=1, max=30),
            retry=retry_if_exception_type(self._retryable),
            before_sleep=lambda state: logger.warning(
                "Retrying Anthropic call (attempt %d)", state.attempt_number
            ),
        )
        return retryer(self._call)(**kwargs)

    def _call(
        self, *, system: str, prompt: str, model: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        try:
            message = self._client.messages.create(
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._retryable:
            raise
        except Exception as exc:
            raise TeacherError(f"Anthropic request failed: {exc}") from exc

        text = "".join(
            getattr(block, "text", "")
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        usage = getattr(message, "usage", None)
        return LLMResponse(
            text=text,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
