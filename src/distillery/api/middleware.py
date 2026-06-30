"""ASGI middleware: request context, metrics, rate limiting and security headers.

Ordering matters. Middleware is applied so that, per request, the outermost is
security headers, then body-size limit, then rate limiting, then request context
(which times the *inner* handler). FastAPI applies the last-added middleware
first, which the app factory accounts for.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from distillery.infrastructure.observability.logging import bind_context, clear_context
from distillery.infrastructure.observability.metrics import METRICS

logger = logging.getLogger("distillery.access")

# Endpoints exempt from authentication-derived rate limiting.
_EXEMPT_PATHS = frozenset(
    {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json", "/"}
)


def _route_template(request: Request) -> str:
    """Return the matched route template (low cardinality) or the raw path."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds log context, times the request and emits metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_context(request_id=request_id, method=request.method, path=request.url.path)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            clear_context()
            raise
        duration = time.perf_counter() - start

        template = _route_template(request)
        METRICS.http_requests_total.labels(
            method=request.method, path=template, status=str(response.status_code)
        ).inc()
        METRICS.http_request_duration_seconds.labels(method=request.method, path=template).observe(
            duration
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{duration * 1000:.2f}"
        logger.info(
            "request",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        clear_context()
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiting keyed by API key or client IP."""

    def __init__(self, app, limiter, header_name: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._limiter = limiter
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        api_key = request.headers.get(self._header_name)
        client = request.client.host if request.client else "anonymous"
        key = f"key:{api_key}" if api_key else f"ip:{client}"
        decision = self._limiter.check(key)

        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Rate limit exceeded.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
                headers=self._headers(decision, retry=True),
            )

        response = await call_next(request)
        for header, value in self._headers(decision).items():
            response.headers[header] = value
        return response

    @staticmethod
    def _headers(decision, retry: bool = False) -> dict[str, str]:  # type: ignore[no-untyped-def]
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_seconds),
        }
        if retry:
            headers["Retry-After"] = str(decision.reset_seconds)
        return headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive HTTP response headers (OWASP secure headers)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "0")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose Content-Length exceeds the configured maximum."""

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request body exceeds {self._max_bytes} bytes.",
                    }
                },
            )
        return await call_next(request)
