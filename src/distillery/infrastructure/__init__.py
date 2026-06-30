"""Infrastructure adapters — concrete implementations of the domain ports.

Everything here depends on a framework or external system (SQLAlchemy, Redis,
Celery, Prometheus, object storage, JWT). The domain and application layers
depend only on the *ports*; these adapters are wired in at the composition root
(:mod:`distillery.api.deps` for the API, the Celery app for the worker).
"""

from __future__ import annotations

__all__: list[str] = []
