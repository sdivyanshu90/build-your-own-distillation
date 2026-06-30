"""Authentication & credential management use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from distillery.config.settings import SecuritySettings
from distillery.domain.entities import ApiKey, User
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError, ConflictError
from distillery.domain.ports import UnitOfWork
from distillery.infrastructure.security.api_keys import generate_api_key
from distillery.infrastructure.security.passwords import hash_password, verify_password
from distillery.infrastructure.security.tokens import create_access_token

logger = logging.getLogger(__name__)


class AuthService:
    """Manages users, password login and API keys."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: SecuritySettings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    def create_user(
        self, *, email: str, password: str | None = None, role: Role = Role.VIEWER
    ) -> User:
        hashed = (
            hash_password(password, iterations=self._settings.password_hash_iterations)
            if password
            else None
        )
        user = User(email=email.lower().strip(), role=role, hashed_password=hashed)
        with self._uow_factory() as uow:
            if uow.users.get_by_email(user.email) is not None:
                raise ConflictError(f"A user with email {user.email} already exists")
            uow.users.add(user)
            uow.commit()
        logger.info("Created user %s (%s)", user.email, role.value)
        return user

    def authenticate_user(self, email: str, password: str) -> User:
        with self._uow_factory() as uow:
            user = uow.users.get_by_email(email.lower().strip())
        if (
            user is None
            or not user.is_active
            or not user.hashed_password
            or not verify_password(password, user.hashed_password)
        ):
            raise AuthenticationError("Invalid email or password")
        return user

    def issue_access_token(self, user: User) -> str:
        return create_access_token(subject=user.id, role=user.role, settings=self._settings)

    def login(self, email: str, password: str) -> str:
        """Authenticate and return a signed access token."""
        return self.issue_access_token(self.authenticate_user(email, password))

    def create_api_key(
        self,
        *,
        owner_id: str,
        name: str,
        role: Role = Role.OPERATOR,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKey, str]:
        """Create an API key and return ``(api_key, plaintext)``.

        The plaintext is shown to the caller exactly once and never stored.
        """
        full_key, prefix, hashed = generate_api_key()
        api_key = ApiKey(
            name=name,
            prefix=prefix,
            hashed_key=hashed,
            owner_id=owner_id,
            role=role,
            expires_at=expires_at,
        )
        with self._uow_factory() as uow:
            if uow.users.get(owner_id) is None:
                raise AuthenticationError("Unknown owner for API key")
            uow.api_keys.add(api_key)
            uow.commit()
        logger.info("Issued API key %s for owner %s", api_key.prefix, owner_id)
        return api_key, full_key

    def list_api_keys(self, owner_id: str) -> Sequence[ApiKey]:
        with self._uow_factory() as uow:
            return uow.api_keys.list_for_owner(owner_id)
