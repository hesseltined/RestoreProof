"""
Purpose: Outbound push notifications via ntfy using stored push settings.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-09-15
Version: 1.2.0
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy.orm import Session

from app.models import RestoreRun
from app.security import decrypt_secret
from app.services.bootstrap import get_push_settings

logger = logging.getLogger(__name__)

# ntfy's JSON API takes a numeric priority; the UI speaks in names.
PRIORITIES: dict[str, int] = {
    "min": 1,
    "low": 2,
    "default": 3,
    "high": 4,
    "urgent": 5,
}

# Keep well below ntfy's message limit; phone notifications truncate anyway.
MAX_MESSAGE_CHARS = 900


class PushConfigError(RuntimeError):
    """Push is not configured well enough to attempt a send."""


def split_topic_url(url: str) -> tuple[str, str]:
    """
    Split an ntfy topic URL into (server_base, topic).

    ``https://ntfy.sh/restoreproof`` → ``("https://ntfy.sh", "restoreproof")``.
    A server behind a path prefix keeps that prefix:
    ``https://host/ntfy/restoreproof`` → ``("https://host/ntfy", "restoreproof")``.
    """
    parts = urlsplit((url or "").strip())
    if not parts.scheme or not parts.netloc:
        raise PushConfigError(
            "Push URL must be a full topic URL, for example https://ntfy.sh/your-topic"
        )
    if parts.scheme not in ("http", "https"):
        raise PushConfigError("Push URL must start with http:// or https://")
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        raise PushConfigError(
            "Push URL is missing the topic name, for example https://ntfy.sh/your-topic"
        )
    prefix = "/".join(segments[:-1])
    base = urlunsplit((parts.scheme, parts.netloc, f"/{prefix}" if prefix else "", "", ""))
    return base, segments[-1]


def _shorten(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def send_push(
    db: Session,
    *,
    title: str,
    message: str,
    priority: str = "default",
    tags: Optional[list[str]] = None,
    click_url: str = "",
    timeout: float = 15.0,
) -> None:
    """
    Publish one notification to the configured ntfy topic.

    Raises ``PushConfigError`` when unconfigured and ``RuntimeError`` when the
    server rejects the publish, so callers can surface the reason verbatim.
    """
    settings = get_push_settings(db)
    base, topic = split_topic_url(settings.url)

    payload: dict[str, Any] = {
        "topic": topic,
        "title": _shorten(title, 250),
        "message": _shorten(message) or "(no details)",
        "priority": PRIORITIES.get(priority, PRIORITIES["default"]),
    }
    if tags:
        payload["tags"] = tags
    if click_url:
        payload["click"] = click_url

    headers: dict[str, str] = {}
    if settings.token_enc:
        headers["Authorization"] = f"Bearer {decrypt_secret(settings.token_enc)}"

    async with httpx.AsyncClient(timeout=timeout, verify=settings.verify_ssl) as client:
        resp = await client.post(f"{base}/", json=payload, headers=headers)
    if resp.status_code >= 400:
        detail = (resp.text or "").strip()[:300]
        raise RuntimeError(f"ntfy rejected the publish: HTTP {resp.status_code} {detail}")


def build_run_push(run: RestoreRun, ctx: dict[str, Any]) -> dict[str, Any]:
    """Short, phone-sized summary of a finished run, with a deep link to it."""
    guest = ctx.get("guest_name") or run.source_name
    vmid = ctx.get("vmid") or run.source_vmid
    run_url = str(ctx.get("run_url") or "")

    # Everything alerts. ntfy maps priority onto Android notification channels, and
    # anything below "high" lands silently in the drawer with no pop-up — which reads
    # as a missed notification. Use the success/failure toggles to choose what is
    # worth sending, rather than sending something you will not notice.
    if run.status == "success":
        if run.used_fallback_backup:
            title = f"RestoreProof passed (older backup) — {guest}"
            tags = ["warning"]
        else:
            title = f"RestoreProof passed — {guest}"
            tags = ["white_check_mark"]
        body = run.result_summary or "Restored from PBS, booted, and verified."
    else:
        title = f"RestoreProof FAILED — {guest}"
        tags = ["rotating_light"]
        body = run.error_message or run.result_summary or "Restore test failed."

    return {
        "title": f"{title} (VMID {vmid})",
        "message": body,
        "priority": "high",
        "tags": tags,
        "click_url": run_url,
    }


def build_digest_push(runs: list[RestoreRun], *, failed: bool, click_url: str) -> dict[str, Any]:
    n = len(runs)
    names = ", ".join((r.source_name or f"VMID {r.source_vmid}") for r in runs[:8])
    extra = f" (+{n - 8} more)" if n > 8 else ""
    if failed:
        title = f"RestoreProof: {n} failed restore test{'s' if n != 1 else ''}"
        tags = ["rotating_light"]
        first_err = (
            (runs[0].error_message or runs[0].result_summary or "Restore test failed.")
            if runs
            else ""
        )
        message = f"{names}{extra}. {first_err}".strip()
    else:
        title = f"RestoreProof: {n} passed restore test{'s' if n != 1 else ''}"
        tags = ["white_check_mark"]
        message = f"{names}{extra}"
    return {
        "title": title,
        "message": _shorten(message),
        "priority": "high",
        "tags": tags,
        "click_url": click_url,
    }


def build_gap_push(payload: dict[str, Any], click_url: str) -> dict[str, Any]:
    hours = payload.get("hours_since")
    hours_label = f"{hours:.0f}h" if hours is not None else "the gap window"
    eligible = int(payload.get("eligible") or 0)
    last_guest = payload.get("last_guest") or "none"
    return {
        "title": f"RestoreProof: no restore tests in {hours_label}",
        "message": _shorten(
            f"Last restore: {last_guest}. Eligible guests: {eligible}. "
            "Scheduler is on but nothing finished."
        ),
        "priority": "high",
        "tags": ["hourglass"],
        "click_url": click_url,
    }
