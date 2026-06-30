"""JWT access-token issuance and verification (HS256 by default)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from distillery.config.settings import SecuritySettings
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError

_ISSUER = "distillery"


def create_access_token(
    *,
    subject: str,
    role: Role,
    settings: SecuritySettings,
    expires_in: int | None = None,
) -> str:
    """Issue a signed JWT for ``subject`` carrying its ``role``."""
    now = datetime.now(timezone.utc)
    ttl = expires_in if expires_in is not None else settings.access_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "iss": _ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: SecuritySettings) -> dict[str, Any]:
    """Verify a JWT and return its claims, or raise :class:`AuthenticationError`."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc
