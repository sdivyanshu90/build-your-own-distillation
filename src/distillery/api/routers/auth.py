"""Authentication and credential-management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from distillery.api.deps import AuthServiceDep, PrincipalDep, SettingsDep, require_role
from distillery.api.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    LoginRequest,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
)
from distillery.domain.enums import Role

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a JWT")
def login(payload: LoginRequest, auth: AuthServiceDep, settings: SettingsDep) -> TokenResponse:
    token = auth.login(payload.email, payload.password)
    return TokenResponse(access_token=token, expires_in=settings.security.access_token_ttl_seconds)


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
    summary="Create a user (admin only)",
)
def create_user(payload: UserCreateRequest, auth: AuthServiceDep) -> UserResponse:
    user = auth.create_user(email=payload.email, password=payload.password, role=payload.role)
    return UserResponse.from_entity(user)


@router.get("/me", response_model=dict, summary="Describe the current principal")
def me(principal: PrincipalDep) -> dict:
    return {
        "subject": principal.subject,
        "role": principal.role.value,
        "auth_method": principal.method,
    }


@router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new API key for the current user",
)
def create_api_key(
    payload: ApiKeyCreateRequest, principal: PrincipalDep, auth: AuthServiceDep
) -> ApiKeyCreateResponse:
    # A caller may not grant a key more privileged than itself.
    role = payload.role if principal.role.rank >= payload.role.rank else principal.role
    api_key, secret = auth.create_api_key(
        owner_id=principal.subject, name=payload.name, role=role, expires_at=payload.expires_at
    )
    return ApiKeyCreateResponse.from_entity_with_secret(api_key, secret)


@router.get("/api-keys", response_model=list[ApiKeyResponse], summary="List your API keys")
def list_api_keys(principal: PrincipalDep, auth: AuthServiceDep) -> list[ApiKeyResponse]:
    return [ApiKeyResponse.from_entity(k) for k in auth.list_api_keys(principal.subject)]
