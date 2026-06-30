"""Authentication and credential-management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from distillery.domain.entities import ApiKey, User
from distillery.domain.enums import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    # Use Field(default=...) rather than a bare string so linters don't mistake
    # the OAuth2 token type for a hardcoded secret (Bandit/ruff S105).
    token_type: str = Field(default="bearer")
    expires_in: int


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=256)
    role: Role = Role.VIEWER


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime

    @classmethod
    def from_entity(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    role: Role = Role.OPERATOR
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    role: Role
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None

    @classmethod
    def from_entity(cls, key: ApiKey) -> ApiKeyResponse:
        return cls(
            id=key.id,
            name=key.name,
            prefix=key.prefix,
            role=key.role,
            is_active=key.is_active,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            expires_at=key.expires_at,
        )


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned once at creation time, including the plaintext key."""

    api_key: str = Field(..., description="The full secret key — shown only once.")

    @classmethod
    def from_entity_with_secret(cls, key: ApiKey, secret: str) -> ApiKeyCreateResponse:
        base = ApiKeyResponse.from_entity(key)
        return cls(**base.model_dump(), api_key=secret)
