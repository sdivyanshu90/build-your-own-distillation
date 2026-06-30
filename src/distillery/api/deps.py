"""FastAPI dependency providers.

Wires request handlers to application services (via the composition root) and
implements authentication + role-based authorization. Security schemes are
declared with ``auto_error=False`` so a single dependency can accept *either* an
API key or a bearer token while still advertising both in the OpenAPI schema.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from distillery import bootstrap
from distillery.application.services.auth_service import AuthService
from distillery.application.services.job_service import JobService
from distillery.config.settings import Settings, get_settings
from distillery.domain.entities import DistillationJob
from distillery.domain.enums import Role
from distillery.domain.exceptions import AuthenticationError, AuthorizationError
from distillery.infrastructure.security.authentication import Authenticator, Principal

_settings = get_settings()
_api_key_scheme = APIKeyHeader(name=_settings.security.api_key_header, auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_job_service() -> JobService:
    return bootstrap.build_job_service()


def get_auth_service() -> AuthService:
    return bootstrap.build_auth_service()


def get_authenticator() -> Authenticator:
    return bootstrap.build_authenticator()


JobServiceDep = Annotated[JobService, Depends(get_job_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_principal(
    api_key: Annotated[str | None, Security(_api_key_scheme)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
    authenticator: Authenticator = Depends(get_authenticator),
) -> Principal:
    """Resolve the caller from an API key or bearer token."""
    if api_key:
        return authenticator.authenticate_api_key(api_key)
    if bearer and bearer.credentials:
        return authenticator.authenticate_bearer(bearer.credentials)
    raise AuthenticationError("Missing API key or bearer token")


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    """Dependency factory enforcing a minimum role."""

    def _checker(principal: PrincipalDep) -> Principal:
        if not principal.has_role(minimum):
            raise AuthorizationError(f"This action requires the '{minimum.value}' role or higher")
        return principal

    return _checker


def authorize_job_access(job: DistillationJob, principal: Principal) -> None:
    """Owners may access their own jobs; admins may access any job."""
    if principal.role is Role.ADMIN or job.owner_id == principal.subject:
        return
    raise AuthorizationError("You do not have access to this job")
