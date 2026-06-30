"""Shared pytest fixtures and lightweight test doubles.

The fixtures here favour fast, hermetic tests: an in-memory SQLite database, a
local temp storage backend, eager (synchronous) job execution and tiny
config-only models that need no network. Heavyweight ML tests are marked ``ml``.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Settings / environment
# ---------------------------------------------------------------------------
@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch, sqlite_url: str, tmp_path: Path) -> None:
    """Configure environment for a hermetic, eager, local test run."""
    monkeypatch.setenv("DISTILLERY_ENV", "development")
    monkeypatch.setenv("DISTILLERY_DATABASE__URL", sqlite_url)
    monkeypatch.setenv("DISTILLERY_QUEUE__EAGER", "true")
    monkeypatch.setenv("DISTILLERY_STORAGE__LOCAL_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DISTILLERY_LOG_FORMAT", "console")
    monkeypatch.setenv("DISTILLERY_SECURITY__BOOTSTRAP_API_KEYS", "test-admin-key-000")
    monkeypatch.setenv("DISTILLERY_SECURITY__JWT_SECRET", "t" * 48)

    from distillery import bootstrap
    from distillery.config.settings import get_settings
    from distillery.infrastructure.db.session import get_session_factory

    get_settings.cache_clear()
    get_session_factory.cache_clear()
    bootstrap.reset_caches()
    yield
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    bootstrap.reset_caches()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@pytest.fixture
def session_factory(sqlite_url: str):
    from distillery.config.settings import DatabaseSettings
    from distillery.infrastructure.db.base import Base
    from distillery.infrastructure.db.session import create_db_engine, create_session_factory

    engine = create_db_engine(DatabaseSettings(url=sqlite_url))
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def uow_factory(session_factory) -> Callable:
    from distillery.infrastructure.db.repositories import SqlAlchemyUnitOfWork

    return lambda: SqlAlchemyUnitOfWork(session_factory)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
@pytest.fixture
def local_storage(tmp_path: Path):
    from distillery.infrastructure.storage.local import LocalArtifactStorage

    return LocalArtifactStorage(root=tmp_path / "store")


# ---------------------------------------------------------------------------
# Domain config builders
# ---------------------------------------------------------------------------
@pytest.fixture
def inline_rows() -> list[dict]:
    return [{"text": f"a wonderful great film {i}", "label": 1} for i in range(8)] + [
        {"text": f"an awful terrible movie {i}", "label": 0} for i in range(8)
    ]


@pytest.fixture
def response_config(inline_rows: list[dict]):
    from distillery.domain.enums import DatasetFormat, DistillationStrategy, TeacherType
    from distillery.domain.value_objects import (
        DatasetSpec,
        DistillationConfig,
        KDHyperParams,
        ModelSpec,
        TrainingConfig,
    )

    return DistillationConfig(
        strategy=DistillationStrategy.RESPONSE_BASED,
        teacher_type=TeacherType.HUGGINGFACE,
        teacher=ModelSpec(name_or_path="t", num_labels=2, config_only=True, max_seq_length=16),
        student=ModelSpec(name_or_path="s", num_labels=2, config_only=True, max_seq_length=16),
        dataset=DatasetSpec(
            format=DatasetFormat.INLINE, inline_rows=inline_rows, label_names=["neg", "pos"]
        ),
        training=TrainingConfig(epochs=1, train_batch_size=4, warmup_ratio=0.0),
        kd=KDHyperParams(temperature=2.0, alpha=0.5),
        device="cpu",
    )


# ---------------------------------------------------------------------------
# Test doubles (ports)
# ---------------------------------------------------------------------------
class FakeLLMClient:
    """A deterministic in-memory LLM client for dataset-builder tests."""

    def __init__(self, *, mode: str = "generate") -> None:
        self.mode = mode
        self.calls: list[dict] = []

    def complete(self, *, system, prompt, model, max_tokens, temperature):
        from distillery.teachers.llm.base import LLMResponse

        self.calls.append({"system": system, "prompt": prompt})
        if self.mode == "generate":
            # Extract the requested count from the prompt (best-effort).
            text = '{"examples": ["synthetic example one", "synthetic example two"]}'
        elif self.mode == "labels":
            text = '{"labels": [{"index": 0, "label": "pos"}, {"index": 1, "label": "neg"}]}'
        elif self.mode == "fenced":
            text = '```json\n{"examples": ["fenced one"]}\n```'
        else:  # malformed
            text = "not json at all"
        return LLMResponse(text=text, input_tokens=10, output_tokens=5)


@pytest.fixture
def fake_llm_client() -> FakeLLMClient:
    return FakeLLMClient()


class RecordingTaskQueue:
    """A TaskQueue double that records enqueues without executing them."""

    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.cancelled: list[str] = []

    def enqueue_distillation(self, job_id: str) -> str:
        self.enqueued.append(job_id)
        return f"task-{job_id}"

    def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)


@pytest.fixture
def recording_queue() -> RecordingTaskQueue:
    return RecordingTaskQueue()


@pytest.fixture
def collecting_publisher():
    from distillery.infrastructure.events import CollectingEventPublisher

    return CollectingEventPublisher()


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
@pytest.fixture
def api_client(configured_env) -> Iterator:
    from fastapi.testclient import TestClient

    from distillery.api.app import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-API-Key": "test-admin-key-000"}
