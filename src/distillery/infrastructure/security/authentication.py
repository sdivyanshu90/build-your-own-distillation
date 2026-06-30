"""Authentication service resolving credentials into a :class:`Principal`.

Two credential types are supported:

* **API key** (``X-API-Key`` header) — looked up by prefix, verified by digest,
  and stamped with a ``last_used_at`` timestamp.
* **Bearer JWT** (``Authorization: Bearer``) — verified and decoded into claims.

The authenticator depends only on the :class:`UnitOfWork` *port*, so it is
storage-agnostic and easy to test with a fake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from distillery.config.settings import SecuritySettings
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError
from distillery.domain.ports import UnitOfWork
from distillery.infrastructure.security.api_keys import extract_prefix, verify_api_key
from distillery.infrastructure.security.tokens import decode_access_token


@dataclass(frozen=True)
class Principal:
    """An authenticated caller and the role it acts with."""

    subject: str
    role: Role
    method: str
    key_id: str | None = None

    def has_role(self, required: Role) -> bool:
        return self.role.rank >= required.rank


class Authenticator:
    """Resolves raw credentials into a :class:`Principal`."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: SecuritySettings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    def authenticate_api_key(self, raw_key: str) -> Principal:
        prefix = extract_prefix(raw_key)
        if not prefix:
            raise AuthenticationError("Malformed API key")
        with self._uow_factory() as uow:
            api_key = uow.api_keys.get_by_prefix(prefix)
            if (
                api_key is None
                or not api_key.is_usable
                or not verify_api_key(raw_key, api_key.hashed_key)
            ):
                raise AuthenticationError("Invalid API key")
            api_key.last_used_at = datetime.now(timezone.utc)
            uow.api_keys.update(api_key)
            uow.commit()
            return Principal(
                subject=api_key.owner_id,
                role=api_key.role,
                method="api_key",
                key_id=api_key.id,
            )

    def authenticate_bearer(self, token: str) -> Principal:
        claims = decode_access_token(token, self._settings)
        try:
            role = Role(claims.get("role", Role.VIEWER.value))
        except ValueError as exc:
            raise AuthenticationError("Token carries an unknown role") from exc
        return Principal(subject=str(claims["sub"]), role=role, method="jwt")
