"""Structured logging via :mod:`structlog`.

Produces machine-parseable JSON logs in production and human-friendly coloured
logs in development. Standard-library logging is routed through the same pipeline
so third-party logs share the format. A ``request_id`` (and any other bound
context) is automatically merged into every event via context variables.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from distillery.config.settings import LogFormat, Settings

_CONFIGURED = False


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    global _CONFIGURED  # noqa: PLW0603 - module-level idempotency guard
    if _CONFIGURED:
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format is LogFormat.JSON:
        renderer: Any = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Tame noisy libraries.
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "urllib3", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.stdlib.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind key/values onto the current context (merged into every log event)."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables (call at the end of a request/task)."""
    structlog.contextvars.clear_contextvars()
