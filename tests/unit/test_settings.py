"""Unit tests for configuration parsing and production guards."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from distillery.config.settings import (
    ApiSettings,
    Environment,
    SecuritySettings,
    Settings,
    get_settings,
)

pytestmark = pytest.mark.unit


def test_defaults() -> None:
    s = Settings()
    assert s.env is Environment.DEVELOPMENT
    assert s.database.pool_size == 10
    assert s.api.port == 8000


def test_nested_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILLERY_DATABASE__POOL_SIZE", "42")
    monkeypatch.setenv("DISTILLERY_API__PORT", "9000")
    s = Settings()
    assert s.database.pool_size == 42
    assert s.api.port == 9000


def test_csv_list_parsing() -> None:
    assert SecuritySettings(bootstrap_api_keys="k1, k2 ,k3").bootstrap_api_keys == [
        "k1",
        "k2",
        "k3",
    ]
    assert ApiSettings(cors_origins='["http://a"]').cors_origins == ["http://a"]
    assert ApiSettings(cors_origins="http://a,http://b").cors_origins == ["http://a", "http://b"]
    assert SecuritySettings(bootstrap_api_keys="").bootstrap_api_keys == []


def test_log_level_validation() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(PydanticValidationError):
        Settings(log_level="verbose")


def test_production_requires_strong_secret() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            env=Environment.PRODUCTION, security=SecuritySettings(jwt_secret=SecretStr("short"))
        )


def test_production_forbids_debug() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            env=Environment.PRODUCTION,
            debug=True,
            security=SecuritySettings(jwt_secret=SecretStr("a" * 40)),
        )


def test_production_ok_with_strong_secret() -> None:
    s = Settings(
        env=Environment.PRODUCTION,
        debug=False,
        security=SecuritySettings(jwt_secret=SecretStr("a" * 40)),
    )
    assert s.env.is_production


def test_get_settings_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
