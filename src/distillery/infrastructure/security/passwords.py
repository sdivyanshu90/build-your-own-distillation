"""Password hashing using PBKDF2-HMAC-SHA256.

A salted, high-iteration KDF with a self-describing, versioned encoding
(``pbkdf2_sha256$iterations$salt$hash``). Verification is constant-time. PBKDF2
is used to avoid a native build dependency; argon2id is a drop-in upgrade if the
``argon2-cffi`` wheel is acceptable in your environment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000
_SALT_BYTES = 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(
    password: str, *, iterations: int = _DEFAULT_ITERATIONS, salt: bytes | None = None
) -> str:
    """Return an encoded PBKDF2 hash of ``password``."""
    if not password:
        raise ValueError("password must not be empty")
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification of ``password`` against an encoded hash."""
    try:
        algo, iterations_s, salt_s, hash_s = encoded.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations_s)
        salt = _unb64(salt_s)
        expected = _unb64(hash_s)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)
