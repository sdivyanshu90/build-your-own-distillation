"""Security primitives: hashing, tokens, authentication and rate limiting."""

from __future__ import annotations

from distillery.infrastructure.security.api_keys import (
    extract_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from distillery.infrastructure.security.authentication import Authenticator, Principal
from distillery.infrastructure.security.passwords import hash_password, verify_password
from distillery.infrastructure.security.rate_limit import (
    InMemoryRateLimiter,
    RateLimitDecision,
    RateLimiter,
    RedisRateLimiter,
)
from distillery.infrastructure.security.tokens import (
    create_access_token,
    decode_access_token,
)

__all__ = [
    "Authenticator",
    "InMemoryRateLimiter",
    "Principal",
    "RateLimitDecision",
    "RateLimiter",
    "RedisRateLimiter",
    "create_access_token",
    "decode_access_token",
    "extract_prefix",
    "generate_api_key",
    "hash_api_key",
    "hash_password",
    "verify_api_key",
    "verify_password",
]
