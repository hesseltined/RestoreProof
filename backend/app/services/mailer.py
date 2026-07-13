"""
Purpose: Outbound email via aiosmtplib using stored SMTP settings.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.1.0
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Optional

import aiosmtplib
from sqlalchemy.orm import Session

from app.security import decrypt_secret
from app.services.bootstrap import get_smtp_settings
from app.services.email_templates import html_to_plain
from app.services.smtp_presets import SMTP_PRESETS

logger = logging.getLogger(__name__)


def apply_preset_defaults(provider: str, data: dict) -> dict:
    preset = SMTP_PRESETS.get(provider, SMTP_PRESETS["generic"])
    if not data.get("host"):
        data["host"] = preset.get("host", "")
    if "port" not in data or data.get("port") is None:
        data["port"] = preset.get("port", 587)
    data.setdefault("use_tls", preset.get("use_tls", True))
    data.setdefault("use_ssl", preset.get("use_ssl", False))
    if provider == "sendgrid" and not data.get("username"):
        data["username"] = "apikey"
    return data


async def send_email(
    db: Session,
    *,
    to_addrs: list[str],
    subject: str,
    body: str,
    cc_addrs: Optional[list[str]] = None,
    inline_images: Optional[list[tuple[str, bytes, str]]] = None,
) -> None:
    smtp = get_smtp_settings(db)
    if not smtp.host or not smtp.from_email:
        raise RuntimeError("SMTP is not configured (host/from_email required)")

    password = decrypt_secret(smtp.password_enc)
    msg = EmailMessage()
    msg["From"] = f"{smtp.from_name} <{smtp.from_email}>" if smtp.from_name else smtp.from_email
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject

    is_html = "<html" in body.lower()
    if is_html:
        msg.set_content(html_to_plain(body))
        msg.add_alternative(body, subtype="html")
        if inline_images:
            html_part = msg.get_payload()[-1]
            for cid, data, subtype in inline_images:
                html_part.add_related(data, "image", subtype, cid=cid)
    else:
        msg.set_content(body)

    recipients = list(to_addrs) + list(cc_addrs or [])

    if smtp.use_ssl:
        await aiosmtplib.send(
            msg,
            hostname=smtp.host,
            port=smtp.port,
            username=smtp.username or None,
            password=password or None,
            use_tls=True,
            recipients=recipients,
        )
    else:
        await aiosmtplib.send(
            msg,
            hostname=smtp.host,
            port=smtp.port,
            username=smtp.username or None,
            password=password or None,
            start_tls=smtp.use_tls,
            recipients=recipients,
        )


def parse_addr_list(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parts = []
    for chunk in raw.replace(";", ",").split(","):
        addr = chunk.strip()
        if addr:
            parts.append(addr)
    return parts
