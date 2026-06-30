"""Strongly-typed application settings backed by environment variables.

All configuration is sourced from the environment (optionally seeded from a
``.env`` file in development), validated by Pydantic, and exposed through the
cached :func:`get_settings` accessor. Nested groups use the ``__`` delimiter,
e.g. ``DISTILLERY_DATABASE__URL``.

Nested groups are plain :class:`pydantic.BaseModel` (not ``BaseSettings``) so the
root settings object is the single env source. List fields that may be supplied
as comma-separated strings carry :class:`pydantic_settings.NoDecode` so that
their custom validators — rather than the JSON decoder — interpret the value.

This module deliberately has **no** dependency on any other Distillery module so
it can be imported from anywhere (Alembic, the CLI, ...) without import cycles.
"""

from __future__ import annotations

import enum
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(str, enum.Enum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is Environment.PRODUCTION


class StorageBackend(str, enum.Enum):
    """Supported artifact storage backends."""

    LOCAL = "local"
    S3 = "s3"


class LogFormat(str, enum.Enum):
    JSON = "json"
    CONSOLE = "console"


def _parse_str_list(value: object) -> object:
    """Accept a JSON array, a comma-separated string, or an actual list."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]
    return value


# ---------------------------------------------------------------------------
# Nested setting groups (plain BaseModel — populated by the root settings)
# ---------------------------------------------------------------------------
class ApiSettings(BaseModel):
    """HTTP server configuration."""

    host: str = "0.0.0.0"  # noqa: S104 — binding all interfaces is intended in containers
    port: int = Field(default=8000, ge=1, le=65535)
    root_path: str = ""
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    docs_enabled: bool = True
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_request_body_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        return _parse_str_list(value)


class SecuritySettings(BaseModel):
    """Authentication, authorisation and rate-limiting configuration."""

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = Field(default=3600, ge=60)
    api_key_header: str = "X-API-Key"
    # Bootstrap keys are hashed at startup; never store plaintext keys at rest.
    bootstrap_api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    rate_limit_per_minute: int = Field(default=120, ge=1)
    password_hash_iterations: int = Field(default=600_000, ge=100_000)

    @field_validator("bootstrap_api_keys", mode="before")
    @classmethod
    def _split_keys(cls, value: object) -> object:
        return _parse_str_list(value)


class DatabaseSettings(BaseModel):
    """PostgreSQL connection + pool configuration."""

    url: str = "postgresql+psycopg://distillery:distillery@localhost:5432/distillery"
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=20, ge=0)
    pool_timeout_seconds: int = Field(default=30, ge=1)
    pool_recycle_seconds: int = Field(default=1800, ge=60)
    echo: bool = False

    @property
    def sync_url(self) -> str:
        """A psycopg (v3) sync URL usable by SQLAlchemy and Alembic."""
        return self.url


class QueueSettings(BaseModel):
    """Celery broker / result-backend configuration."""

    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    task_time_limit_seconds: int = Field(default=86_400, ge=60)
    task_soft_time_limit_seconds: int = Field(default=82_800, ge=60)
    worker_concurrency: int = Field(default=2, ge=1)
    task_max_retries: int = Field(default=3, ge=0)
    visibility_timeout_seconds: int = Field(default=90_000, ge=60)
    #: Execute jobs synchronously in-process instead of via Celery (dev/tests).
    eager: bool = False


class StorageSettings(BaseModel):
    """Artifact storage configuration."""

    backend: StorageBackend = StorageBackend.LOCAL
    local_root: Path = Path("./artifacts")
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_prefix: str = "distillery"


class LLMSettings(BaseModel):
    """LLM teacher provider configuration."""

    provider: str = "anthropic"
    anthropic_api_key: SecretStr = SecretStr("")
    default_teacher_model: str = "claude-sonnet-4-6"
    max_concurrency: int = Field(default=4, ge=1)
    request_timeout_seconds: int = Field(default=120, ge=1)
    max_retries: int = Field(default=5, ge=0)
    max_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class TrainingSettings(BaseModel):
    """Default training/runtime knobs for the distillation engine."""

    device: str = "auto"  # auto | cpu | cuda | mps
    default_seed: int = 42
    max_epochs: int = Field(default=3, ge=1)
    mixed_precision: bool = False
    dataloader_num_workers: int = Field(default=2, ge=0)
    gradient_clip_norm: float = Field(default=1.0, ge=0.0)
    checkpoint_every_n_steps: int = Field(default=0, ge=0)  # 0 = epoch only


class ObservabilitySettings(BaseModel):
    """Metrics / tracing configuration."""

    metrics_enabled: bool = True
    metrics_port: int = Field(default=9100, ge=1, le=65535)
    tracing_enabled: bool = False
    otlp_endpoint: str = ""


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """Top-level application settings aggregating every group."""

    model_config = SettingsConfigDict(
        env_prefix="DISTILLERY_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    service_name: str = "distillery-api"

    api: ApiSettings = Field(default_factory=ApiSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    training: TrainingSettings = Field(default_factory=TrainingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    def model_post_init(self, __context: object) -> None:
        """Fail fast on insecure production configuration."""
        if self.env.is_production:
            secret = self.security.jwt_secret.get_secret_value()
            if secret in {"", "change-me", "change-me-in-production"} or len(secret) < 32:
                raise ValueError(
                    "A strong DISTILLERY_SECURITY__JWT_SECRET (>=32 chars) is required "
                    "in production."
                )
            if self.debug:
                raise ValueError("DISTILLERY_DEBUG must be false in production.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide, cached :class:`Settings` instance.

    Cached so that configuration is parsed exactly once. Call
    ``get_settings.cache_clear()`` in tests to force a reload.
    """
    return Settings()
