"""Unit tests for hashing, API keys and JWTs."""

from __future__ import annotations

from datetime import timedelta

import pytest

from distillery.config.settings import SecuritySettings
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError
from distillery.infrastructure.security.api_keys import (
    PREFIX_LENGTH,
    extract_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from distillery.infrastructure.security.passwords import hash_password, verify_password
from distillery.infrastructure.security.tokens import create_access_token, decode_access_token

pytestmark = pytest.mark.unit

# Low iteration count keeps password tests fast.
_FAST = 100_000


def test_password_round_trip() -> None:
    encoded = hash_password("correct horse battery", iterations=_FAST)
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("wrong", encoded)


def test_password_unique_salts() -> None:
    assert hash_password("same", iterations=_FAST) != hash_password("same", iterations=_FAST)


def test_password_empty_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_password_malformed_encoded() -> None:
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "bcrypt$1$salt$hash")


def test_api_key_generation_and_verification() -> None:
    full, prefix, hashed = generate_api_key()
    assert full.startswith("dst_")
    assert len(prefix) == PREFIX_LENGTH
    assert extract_prefix(full) == prefix
    assert verify_api_key(full, hashed)
    assert not verify_api_key("dst_wrong", hashed)


def test_api_key_hash_deterministic() -> None:
    assert hash_api_key("dst_abc") == hash_api_key("dst_abc")


def test_extract_prefix_arbitrary_key() -> None:
    assert extract_prefix("bootstrap-admin-key") == "bootstrap-"
    assert extract_prefix("short") is None
    assert extract_prefix("") is None


def _settings() -> SecuritySettings:
    return SecuritySettings(jwt_secret="a" * 40, access_token_ttl_seconds=3600)


def test_jwt_round_trip() -> None:
    settings = _settings()
    token = create_access_token(subject="user-1", role=Role.OPERATOR, settings=settings)
    claims = decode_access_token(token, settings)
    assert claims["sub"] == "user-1"
    assert claims["role"] == "operator"


def test_jwt_expired() -> None:
    settings = _settings()
    token = create_access_token(subject="u", role=Role.VIEWER, settings=settings, expires_in=-1)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings)


def test_jwt_tampered() -> None:
    settings = _settings()
    token = create_access_token(subject="u", role=Role.VIEWER, settings=settings)
    with pytest.raises(AuthenticationError):
        decode_access_token(token + "x", settings)


def test_jwt_wrong_secret() -> None:
    token = create_access_token(subject="u", role=Role.VIEWER, settings=_settings())
    other = SecuritySettings(jwt_secret="b" * 40)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, other)


def test_token_ttl_default(monkeypatch) -> None:
    settings = SecuritySettings(jwt_secret="a" * 40, access_token_ttl_seconds=60)
    token = create_access_token(subject="u", role=Role.ADMIN, settings=settings)
    claims = decode_access_token(token, settings)
    assert claims["exp"] - claims["iat"] == 60
    _ = timedelta  # referenced for clarity
