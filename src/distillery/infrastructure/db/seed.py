"""Database schema creation and bootstrap seeding.

``ensure_schema`` is a convenience for development/tests (production uses Alembic
migrations). ``seed_bootstrap`` provisions a system admin user and registers the
bootstrap API keys from configuration so an operator can make the first
authenticated call right after deployment.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Engine

from distillery.config.settings import SecuritySettings
from distillery.domain.entities import ApiKey, User
from distillery.domain.enums import Role
from distillery.domain.ports import UnitOfWork
from distillery.infrastructure.security.api_keys import extract_prefix, hash_api_key

logger = logging.getLogger(__name__)

SYSTEM_USER_EMAIL = "system@distillery.local"


def ensure_schema(engine: Engine) -> None:
    """Create all tables if they do not exist (dev/test convenience)."""
    from distillery.infrastructure.db import models  # noqa: F401 — registers tables
    from distillery.infrastructure.db.base import Base

    Base.metadata.create_all(engine)


def seed_bootstrap(uow_factory: Callable[[], UnitOfWork], security: SecuritySettings) -> int:
    """Ensure the system user and bootstrap API keys exist. Returns keys added."""
    added = 0
    with uow_factory() as uow:
        user = uow.users.get_by_email(SYSTEM_USER_EMAIL)
        if user is None:
            user = User(email=SYSTEM_USER_EMAIL, role=Role.ADMIN)
            uow.users.add(user)

        for raw_key in security.bootstrap_api_keys:
            prefix = extract_prefix(raw_key)
            if prefix is None:
                logger.warning("Skipping bootstrap key shorter than the prefix length")
                continue
            if uow.api_keys.get_by_prefix(prefix) is not None:
                continue
            uow.api_keys.add(
                ApiKey(
                    name="bootstrap",
                    prefix=prefix,
                    hashed_key=hash_api_key(raw_key),
                    owner_id=user.id,
                    role=Role.ADMIN,
                )
            )
            added += 1
        uow.commit()
    if added:
        logger.info("Seeded %d bootstrap API key(s)", added)
    return added
