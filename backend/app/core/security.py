"""Password hashing, JWT issuing/verifying, and authentication helpers.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, formatted as
``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``. The salt is generated
per-password, so equal passwords do not produce equal stored values.
"""
from __future__ import annotations

import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings


_PBKDF2_ITERATIONS = 260_000
_PBKDF2_ALGO = "sha256"
_SALT_BYTES = 16
_HASH_BYTES = 32

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto", pbkdf2_sha256__default_rounds=_PBKDF2_ITERATIONS)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(plain_password: str) -> str:
    """Return ``pbkdf2_sha256$...$salt$hash`` for the given password."""
    if not plain_password:
        raise ValueError("password must be non-empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _pwd_context.hash(plain_password, salt=salt)
    return digest


def verify_password(plain_password: str, stored_hash: str) -> bool:
    if not plain_password or not stored_hash:
        return False
    try:
        return _pwd_context.verify(plain_password, stored_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        return None


def random_token() -> str:
    return secrets.token_urlsafe(32)
