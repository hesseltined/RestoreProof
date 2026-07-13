"""
Purpose: Fail fast on empty SECRET_KEY or unsafe DB password characters.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.0.1
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urlparse

from app.config import Settings

logger = logging.getLogger(__name__)

# Characters that break YAML comments (#), URL authority (# @ : / ? %), or env parsing.
_UNSAFE_DB_PASSWORD_CHARS = frozenset("#@:/?%&`'\"\\ \t\n\r")

_PLACEHOLDER_SECRETS = frozenset(
    {
        "change-me",
        "change-me-to-a-long-random-string-at-least-32-chars",
        "dev-secret-change-me-to-a-long-random-string",
        "changeme",
        "secret",
        "password",
        "replace-with-openssl-rand-hex-32",
        "replace-with-openssl-rand-hex-24",
    }
)


def _database_password(database_url: str) -> str | None:
    """
    Extract password from SQLAlchemy/postgres URL (handles postgresql+psycopg).

    Uses a regex on the raw URL first so characters like '#' are not lost to
    URL fragment parsing (which would hide the unsafe-character problem).
    """
    raw = database_url.strip()
    if not raw:
        return None
    match = re.search(r"://[^:/@]+:([^@]+)@", raw)
    if match:
        return match.group(1)
    normalized = re.sub(r"^postgresql\+[^:]+://", "postgresql://", raw, count=1)
    parsed = urlparse(normalized)
    if parsed.password is None:
        return None
    return unquote(parsed.password)


def validate_runtime_secrets(settings: Settings, *, role: str = "api") -> None:
    """
    Refuse to start when secrets would cause silent decrypt failures or DB auth loops.

    Portainer/YAML guidance: generate hex-only values (see PORTAINER.md).
    """
    secret = (settings.secret_key or "").strip()
    if not secret:
        raise RuntimeError(
            f"{role}: SECRET_KEY / API_SECRET_KEY is empty. Set the same strong value on "
            "api and worker (openssl rand -hex 32)."
        )
    if len(secret) < 32:
        raise RuntimeError(
            f"{role}: SECRET_KEY / API_SECRET_KEY must be at least 32 characters "
            "(openssl rand -hex 32)."
        )
    if secret.lower() in _PLACEHOLDER_SECRETS:
        logger.warning(
            "%s: SECRET_KEY still looks like a placeholder — change it before any "
            "network-exposed deploy (openssl rand -hex 32)",
            role,
        )

    password = _database_password(settings.database_url)
    if password is None:
        logger.warning(
            "%s: could not parse password from DATABASE_URL — skipping charset check",
            role,
        )
        return

    if password.lower() in _PLACEHOLDER_SECRETS or password in {
        "restoreproof",
        "change-me-strong-password",
    }:
        logger.warning(
            "%s: DATABASE_URL password looks like a default/placeholder — change it "
            "before production (openssl rand -hex 24)",
            role,
        )

    bad = sorted({ch for ch in password if ch in _UNSAFE_DB_PASSWORD_CHARS})
    if bad:
        raise RuntimeError(
            f"{role}: POSTGRES_PASSWORD / DATABASE_URL password contains unsafe characters "
            f"{bad!r}. These break YAML (# starts a comment), URL parsing (# fragment), or "
            "shell/env substitution. Use alphanumeric only, e.g. openssl rand -hex 24. "
            "If the DB volume was already created with a different password, either ALTER the "
            "role password or recreate the rp_pgdata volume."
        )
