"""API-key generation, hashing and verification.

A key looks like ``dst_<token>`` where ``token`` is 256 bits of URL-safe entropy.
The first :data:`PREFIX_LENGTH` characters of the token are stored in clear text
as an indexed lookup handle; the full key is stored only as a SHA-256 digest.
Because keys are high-entropy, a fast cryptographic hash is sufficient (a slow
KDF is unnecessary and would needlessly tax every request).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PREFIX = "dst_"
PREFIX_LENGTH = 10


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new key.

    Returns:
        ``(full_key, prefix, hashed_key)``. The full key is shown to the user
        exactly once; only ``prefix`` and ``hashed_key`` are persisted.
    """
    token = secrets.token_urlsafe(32)
    full_key = f"{_PREFIX}{token}"
    prefix = token[:PREFIX_LENGTH]
    return full_key, prefix, hash_api_key(full_key)


def extract_prefix(full_key: str) -> str | None:
    """Extract the lookup prefix from a presented key, or ``None`` if too short.

    Generated keys carry the ``dst_`` marker, which is stripped before taking the
    prefix. Arbitrary admin-supplied bootstrap keys (without the marker) are also
    supported: their first :data:`PREFIX_LENGTH` characters become the prefix.
    """
    if not full_key:
        return None
    token = full_key[len(_PREFIX) :] if full_key.startswith(_PREFIX) else full_key
    if len(token) < PREFIX_LENGTH:
        return None
    return token[:PREFIX_LENGTH]


def hash_api_key(full_key: str) -> str:
    """Return the SHA-256 hex digest of a full key."""
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def verify_api_key(full_key: str, hashed_key: str) -> bool:
    """Constant-time comparison of a presented key against its stored digest."""
    return hmac.compare_digest(hash_api_key(full_key), hashed_key)
