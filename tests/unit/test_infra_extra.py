"""Targeted tests covering adapter edges, seeding, logging and device logic."""

from __future__ import annotations

import pytest

from distillery.config.settings import LogFormat, SecuritySettings, Settings, StorageSettings
from distillery.infrastructure.security.rate_limit import RedisRateLimiter

pytestmark = pytest.mark.unit


# -- build_engine / build_storage -------------------------------------------
def test_build_engine_returns_default() -> None:
    pytest.importorskip("torch")
    from distillery.core import build_engine
    from distillery.core.engine import DefaultDistillationEngine

    assert isinstance(build_engine(), DefaultDistillationEngine)


def test_build_storage_local(tmp_path) -> None:
    from distillery.infrastructure.storage import build_storage
    from distillery.infrastructure.storage.local import LocalArtifactStorage

    storage = build_storage(StorageSettings(local_root=tmp_path))
    assert isinstance(storage, LocalArtifactStorage)


# -- task queue --------------------------------------------------------------
def test_inline_task_queue_executes() -> None:
    from distillery.infrastructure.queue.adapters import InlineTaskQueue

    seen: list[str] = []
    queue = InlineTaskQueue(seen.append)
    task_id = queue.enqueue_distillation("job-1")
    assert seen == ["job-1"]
    assert task_id == "inline-job-1"
    assert queue.cancel("anything") is None


# -- redis rate limiter (fake client) ---------------------------------------
class _FakePipe:
    def __init__(self, store: dict) -> None:
        self._store = store
        self._bucket: str | None = None

    def incr(self, key: str) -> None:
        self._bucket = key
        self._store[key] = self._store.get(key, 0) + 1

    def expire(self, key: str, ttl: int) -> None:
        return None

    def execute(self) -> list:
        return [self._store[self._bucket], True]


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict = {}

    def pipeline(self) -> _FakePipe:
        return _FakePipe(self.store)


def test_redis_rate_limiter_blocks_after_limit() -> None:
    limiter = RedisRateLimiter(_FakeRedis(), limit_per_minute=2)
    results = [limiter.check("k").allowed for _ in range(3)]
    assert results == [True, True, False]


# -- seeding -----------------------------------------------------------------
def test_seed_bootstrap_idempotent(uow_factory) -> None:
    from distillery.infrastructure.db.seed import seed_bootstrap

    security = SecuritySettings(bootstrap_api_keys=["valid-bootstrap-key", "x"])
    added = seed_bootstrap(uow_factory, security)
    assert added == 1  # the too-short "x" is skipped
    assert seed_bootstrap(uow_factory, security) == 0  # idempotent


# -- logging -----------------------------------------------------------------
def test_configure_logging_json(monkeypatch) -> None:
    import distillery.infrastructure.observability.logging as log_module

    monkeypatch.setattr(log_module, "_CONFIGURED", False)
    log_module.configure_logging(Settings(log_format=LogFormat.JSON))
    log_module.bind_context(request_id="abc")
    logger = log_module.get_logger("test")
    logger.info("hello", key="value")
    log_module.clear_context()
    monkeypatch.setattr(log_module, "_CONFIGURED", False)


# -- device resolution -------------------------------------------------------
def test_resolve_device_cuda_when_available(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    from distillery.core import models

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert models.resolve_device("cuda").type == "cuda"
    assert models.resolve_device("auto").type == "cuda"


def test_resolve_device_cuda_unavailable(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    from distillery.core import models

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(RuntimeError):
        models.resolve_device("cuda")
    assert models.resolve_device("auto").type == "cpu"


def test_resolve_device_mps_when_available(monkeypatch) -> None:
    torch = pytest.importorskip("torch")
    from distillery.core import models

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert models.resolve_device("mps").type == "mps"
