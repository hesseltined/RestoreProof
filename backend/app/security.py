"""
Purpose: Password hashing, JWT, Fernet secret encryption, TOTP helpers.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.0.1
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, extra: Optional[dict[str, Any]] = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def safe_decode_token(token: str) -> Optional[dict[str, Any]]:
    try:
        return decode_access_token(token)
    except JWTError:
        return None


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.encryption_key.strip()
    if not key:
        # Derive stable Fernet key from SECRET_KEY for single-node installs
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    elif len(key) != 44:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Stored secret cannot be decrypted with the current SECRET_KEY. "
            "Re-enter the Proxmox API token secret (and SMTP password if set), "
            "or restore the original SECRET_KEY used when this config was saved."
        ) from exc


def generate_reset_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, token_hash


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str, issuer: str = "RestoreProof") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
