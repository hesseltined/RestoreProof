"""
Purpose: Dead-man's-switch heartbeat ping so a stopped worker gets noticed.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.0.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.models import HeartbeatSettings
from app.services.bootstrap import get_heartbeat_settings

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 86_400


class HeartbeatConfigError(RuntimeError):
    """Heartbeat is not configured well enough to ping."""


def validate_url(url: str) -> str:
    """Accept any http(s) ping URL; query strings are preserved as given."""
    cleaned = (url or "").strip()
    parts = urlsplit(cleaned)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HeartbeatConfigError(
            "Heartbeat URL must be a full http:// or https:// URL, for example "
            "http://uptime-kuma:3001/api/push/AbC123"
        )
    return cleaned


def due_for_ping(settings: HeartbeatSettings, now: datetime | None = None) -> bool:
    """True when the configured interval has elapsed since the last success."""
    if not settings.enabled or not (settings.url or "").strip():
        return False
    if settings.last_ping_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    last = settings.last_ping_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    interval = max(MIN_INTERVAL_SECONDS, int(settings.interval_seconds or 300))
    return now - last >= timedelta(seconds=interval)


def send_heartbeat(db: Session, *, timeout: float = 10.0) -> None:
    """
    Ping the configured URL once. Raises on config problems or HTTP errors.

    A bare GET is what Uptime Kuma push monitors, Healthchecks.io, and Cronitor
    all treat as "alive", so no provider-specific handling is needed.
    """
    settings = get_heartbeat_settings(db)
    url = validate_url(settings.url)
    with httpx.Client(timeout=timeout, verify=settings.verify_ssl, follow_redirects=True) as client:
        resp = client.get(url)
    if resp.status_code >= 400:
        detail = (resp.text or "").strip()[:200]
        raise RuntimeError(f"Heartbeat ping failed: HTTP {resp.status_code} {detail}")


def maybe_send_heartbeat(db: Session) -> bool:
    """
    Ping if enabled and due. Never raises — a monitoring outage must not stop
    the worker, and a failed ping is itself the signal the monitor reacts to.
    """
    settings = get_heartbeat_settings(db)
    if not due_for_ping(settings):
        return False
    try:
        send_heartbeat(db)
    except Exception as exc:  # noqa: BLE001
        settings.last_error = str(exc)[:500]
        db.commit()
        logger.warning("Heartbeat ping failed: %s", exc)
        return False
    settings.last_ping_at = datetime.now(timezone.utc)
    settings.last_error = ""
    db.commit()
    return True
