"""Prometheus metrics.

A single :class:`Metrics` facade owns every collector so call sites stay tidy
and metric names are defined in one place. The API exposes them at ``/metrics``
via :func:`render_latest`; the worker starts a dedicated metrics HTTP server via
:func:`start_metrics_server`.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

# Bucket boundaries (seconds) suited to both fast HTTP calls and long jobs.
_HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_JOB_BUCKETS = (1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 21600, 86400)


class Metrics:
    """Facade over the platform's Prometheus collectors."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry
        kwargs: dict[str, Any] = {"registry": registry} if registry is not None else {}

        self.http_requests_total = Counter(
            "distillery_http_requests_total",
            "Total HTTP requests.",
            ["method", "path", "status"],
            **kwargs,
        )
        self.http_request_duration_seconds = Histogram(
            "distillery_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            ["method", "path"],
            buckets=_HTTP_BUCKETS,
            **kwargs,
        )
        self.jobs_created_total = Counter(
            "distillery_jobs_created_total",
            "Distillation jobs created.",
            ["strategy"],
            **kwargs,
        )
        self.jobs_finished_total = Counter(
            "distillery_jobs_finished_total",
            "Distillation jobs that reached a terminal state.",
            ["status"],
            **kwargs,
        )
        self.job_duration_seconds = Histogram(
            "distillery_job_duration_seconds",
            "Wall-clock duration of distillation jobs in seconds.",
            buckets=_JOB_BUCKETS,
            **kwargs,
        )
        self.jobs_in_progress = Gauge(
            "distillery_jobs_in_progress",
            "Distillation jobs currently running.",
            **kwargs,
        )
        self.llm_teacher_tokens_total = Counter(
            "distillery_llm_teacher_tokens_total",
            "Tokens consumed from LLM teachers.",
            **kwargs,
        )


# Process-wide default facade (uses the global Prometheus registry).
METRICS = Metrics()


def render_latest() -> tuple[bytes, str]:
    """Render the default registry for the ``/metrics`` endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST


def start_metrics_server(port: int) -> None:  # pragma: no cover - binds a socket
    """Start a standalone metrics HTTP server (used by the Celery worker)."""
    start_http_server(port)
