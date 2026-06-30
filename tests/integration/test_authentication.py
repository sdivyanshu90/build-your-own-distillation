"""Integration tests for the Authenticator against a real repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from distillery.config.settings import SecuritySettings
from distillery.domain.entities import ApiKey, User
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError
from distillery.infrastructure.security.api_keys import generate_api_key
from distillery.infrastructure.security.authentication import Authenticator
from distillery.infrastructure.security.tokens import create_access_token

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> SecuritySettings:
    return SecuritySettings(jwt_secret="x" * 40)


@pytest.fixture
def seeded(uow_factory):
    full, prefix, hashed = generate_api_key()
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io", role=Role.OPERATOR))
        uow.api_keys.add(
            ApiKey(name="k", prefix=prefix, hashed_key=hashed, owner_id=user.id, role=Role.OPERATOR)
        )
        uow.commit()
        uid = user.id
    return full, uid


def test_authenticate_api_key(uow_factory, settings, seeded) -> None:
    full, uid = seeded
    authn = Authenticator(uow_factory, settings)
    principal = authn.authenticate_api_key(full)
    assert principal.subject == uid
    assert principal.role is Role.OPERATOR
    assert principal.method == "api_key"


def test_authenticate_api_key_updates_last_used(uow_factory, settings, seeded) -> None:
    full, _ = seeded
    Authenticator(uow_factory, settings).authenticate_api_key(full)
    with uow_factory() as uow:
        key = uow.api_keys.get_by_prefix(full[len("dst_") :][:10])
        assert key.last_used_at is not None


def test_invalid_and_malformed_keys(uow_factory, settings) -> None:
    authn = Authenticator(uow_factory, settings)
    with pytest.raises(AuthenticationError):
        authn.authenticate_api_key("short")
    with pytest.raises(AuthenticationError):
        authn.authenticate_api_key("dst_unknownkey1234567890")


def test_expired_key_rejected(uow_factory, settings) -> None:
    full, prefix, hashed = generate_api_key()
    with uow_factory() as uow:
        user = uow.users.add(User(email="o@x.io"))
        uow.api_keys.add(
            ApiKey(
                name="k",
                prefix=prefix,
                hashed_key=hashed,
                owner_id=user.id,
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )
        uow.commit()
    with pytest.raises(AuthenticationError):
        Authenticator(uow_factory, settings).authenticate_api_key(full)


def test_bearer_authentication(uow_factory, settings) -> None:
    token = create_access_token(subject="user-9", role=Role.ADMIN, settings=settings)
    principal = Authenticator(uow_factory, settings).authenticate_bearer(token)
    assert principal.subject == "user-9"
    assert principal.role is Role.ADMIN
    assert principal.method == "jwt"
