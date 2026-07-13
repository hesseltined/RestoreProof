"""
Purpose: Export and import RestoreProof configuration for VM rebuild or migration.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.0.0
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models import Guest, ProxmoxHost, RestoreRun, User
from app.services.bootstrap import get_app_settings, get_smtp_settings
from app.services.scheduler import refresh_guest_due_times
from app.services.ssh_keys import generate_host_ssh_key, host_key_paths

EXPORT_FORMAT_VERSION = "1.0"

APP_SETTINGS_FIELDS = (
    "branding_title",
    "boot_wait_seconds",
    "retention_days",
    "retention_max_runs",
    "global_cron",
    "schedule_enabled",
    "schedule_batch_size",
    "schedule_coverage_goal",
    "enforce_2fa",
    "setup_completed",
    "notify_on_success",
    "notify_on_failure",
    "notify_to",
    "notify_cc",
    "email_success_subject",
    "email_failure_subject",
    "email_success_body",
    "email_failure_body",
)

SMTP_SETTINGS_FIELDS = (
    "provider",
    "host",
    "port",
    "use_tls",
    "use_ssl",
    "username",
    "password_enc",
    "from_email",
    "from_name",
)

HOST_FIELDS = (
    "name",
    "api_url",
    "token_id",
    "token_secret_enc",
    "verify_ssl",
    "ssh_host",
    "ssh_port",
    "ssh_user",
    "preferred_restore_storage",
    "test_vmid_start",
    "test_vmid_end",
    "enabled",
)


def _dt_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_dict(obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


def _read_ssh_key_bundle(host_id: int) -> dict[str, str] | None:
    private_path, public_path = host_key_paths(host_id)
    if not private_path.exists():
        return None
    private_pem = private_path.read_text(encoding="utf-8")
    public_key = public_path.read_text(encoding="utf-8").strip() if public_path.exists() else ""
    return {"private_pem": private_pem, "public_key": public_key}


def _write_ssh_key_bundle(host_id: int, bundle: dict[str, str] | None) -> str:
    if not bundle or not bundle.get("private_pem"):
        private_path, _pub = generate_host_ssh_key(host_id)
        return str(private_path)

    private_path, public_path = host_key_paths(host_id)
    private_path.write_text(bundle["private_pem"], encoding="utf-8")
    private_path.chmod(0o600)
    public_key = bundle.get("public_key", "").strip()
    if public_key:
        if not public_key.endswith("\n"):
            public_key += "\n"
        public_path.write_text(public_key, encoding="utf-8")
        public_path.chmod(0o644)
    return str(private_path)


def assert_import_allowed(db: Session) -> None:
    active = (
        db.query(RestoreRun)
        .filter(RestoreRun.status.in_(("queued", "running")))
        .count()
    )
    if active:
        raise ValueError("Cannot import while restore runs are queued or running")


def build_export_bundle(db: Session, *, include_users: bool = False) -> dict[str, Any]:
    settings = get_app_settings(db)
    smtp = get_smtp_settings(db)
    hosts = db.query(ProxmoxHost).order_by(ProxmoxHost.id).all()

    host_rows: list[dict[str, Any]] = []
    guest_overrides: list[dict[str, Any]] = []
    ssh_keys: dict[str, dict[str, str]] = {}

    for host in hosts:
        host_rows.append(_row_dict(host, HOST_FIELDS))
        key_bundle = _read_ssh_key_bundle(host.id)
        if key_bundle:
            ssh_keys[host.name] = key_bundle
        for guest in host.guests:
            guest_overrides.append(
                {
                    "host_name": host.name,
                    "vmid": guest.vmid,
                    "excluded": guest.excluded,
                    "schedule_cron": guest.schedule_cron,
                    "schedule_enabled": guest.schedule_enabled,
                    "last_tested_at": _dt_iso(guest.last_tested_at),
                    "next_due_at": _dt_iso(guest.next_due_at),
                }
            )

    users: list[dict[str, Any]] = []
    if include_users:
        for user in db.query(User).order_by(User.id).all():
            users.append(
                {
                    "email": user.email,
                    "password_hash": user.password_hash,
                    "is_active": user.is_active,
                    "is_admin": user.is_admin,
                    "totp_secret": user.totp_secret,
                    "totp_enabled": user.totp_enabled,
                }
            )

    return {
        "format_version": EXPORT_FORMAT_VERSION,
        "app": "RestoreProof",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "secrets_note": (
            "SMTP passwords and Proxmox API token secrets are stored encrypted. "
            "Import on a new VM requires the same SECRET_KEY or ENCRYPTION_KEY in .env."
        ),
        "app_settings": _row_dict(settings, APP_SETTINGS_FIELDS),
        "smtp_settings": _row_dict(smtp, SMTP_SETTINGS_FIELDS),
        "proxmox_hosts": host_rows,
        "guest_overrides": guest_overrides,
        "ssh_keys": ssh_keys,
        "users": users,
    }


def export_config_json(db: Session, *, include_users: bool = False) -> str:
    bundle = build_export_bundle(db, include_users=include_users)
    return json.dumps(bundle, indent=2, sort_keys=False)


def import_config_bundle(
    db: Session,
    bundle: dict[str, Any],
    *,
    mode: Literal["merge", "replace"] = "merge",
    import_users: bool = False,
) -> dict[str, Any]:
    assert_import_allowed(db)

    version = str(bundle.get("format_version", ""))
    if version != EXPORT_FORMAT_VERSION:
        raise ValueError(f"Unsupported export format version: {version or 'missing'}")

    summary = {
        "mode": mode,
        "hosts_created": 0,
        "hosts_updated": 0,
        "guest_overrides_applied": 0,
        "guest_overrides_pending": 0,
        "users_created": 0,
        "users_skipped": 0,
    }

    if mode == "replace":
        db.query(RestoreRun).delete(synchronize_session=False)
        db.query(Guest).delete(synchronize_session=False)
        db.query(ProxmoxHost).delete(synchronize_session=False)
        db.flush()

    app_data = bundle.get("app_settings") or {}
    settings = get_app_settings(db)
    for field in APP_SETTINGS_FIELDS:
        if field in app_data:
            setattr(settings, field, app_data[field])

    smtp_data = bundle.get("smtp_settings") or {}
    smtp = get_smtp_settings(db)
    for field in SMTP_SETTINGS_FIELDS:
        if field in smtp_data:
            setattr(smtp, field, smtp_data[field])
    smtp.smtp_ok_at = None

    ssh_keys: dict[str, dict[str, str]] = bundle.get("ssh_keys") or {}
    hosts_by_name: dict[str, ProxmoxHost] = {}

    if mode == "merge":
        for existing in db.query(ProxmoxHost).all():
            hosts_by_name[existing.name] = existing

    for host_data in bundle.get("proxmox_hosts") or []:
        name = str(host_data.get("name", "")).strip()
        if not name:
            continue
        host = hosts_by_name.get(name)
        created = False
        if not host:
            host = ProxmoxHost(name=name)
            db.add(host)
            db.flush()
            hosts_by_name[name] = host
            created = True

        for field in HOST_FIELDS:
            if field == "name":
                continue
            if field in host_data:
                setattr(host, field, host_data[field])

        host.ssh_private_key_path = _write_ssh_key_bundle(host.id, ssh_keys.get(name))
        host.last_sync_at = None
        host.api_ok_at = None
        host.ssh_ok_at = None
        host.last_error = None

        if created:
            summary["hosts_created"] += 1
        else:
            summary["hosts_updated"] += 1

    db.flush()

    for override in bundle.get("guest_overrides") or []:
        host_name = str(override.get("host_name", "")).strip()
        vmid = override.get("vmid")
        if not host_name or vmid is None:
            continue
        host = hosts_by_name.get(host_name)
        if not host:
            summary["guest_overrides_pending"] += 1
            continue

        guest = (
            db.query(Guest)
            .filter(Guest.host_id == host.id, Guest.vmid == int(vmid))
            .first()
        )
        if not guest:
            guest = Guest(
                host_id=host.id,
                vmid=int(vmid),
                guest_type="qemu",
                name=f"guest-{vmid}",
            )
            db.add(guest)
            db.flush()

        guest.excluded = bool(override.get("excluded", guest.excluded))
        if "schedule_cron" in override:
            guest.schedule_cron = override.get("schedule_cron")
        guest.schedule_enabled = bool(
            override.get("schedule_enabled", guest.schedule_enabled)
        )
        guest.last_tested_at = _parse_dt(override.get("last_tested_at"))
        guest.next_due_at = _parse_dt(override.get("next_due_at"))
        summary["guest_overrides_applied"] += 1

    if import_users:
        for user_data in bundle.get("users") or []:
            email = str(user_data.get("email", "")).lower().strip()
            if not email:
                continue
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                summary["users_skipped"] += 1
                continue
            db.add(
                User(
                    email=email,
                    password_hash=user_data.get("password_hash") or "",
                    is_active=bool(user_data.get("is_active", True)),
                    is_admin=bool(user_data.get("is_admin", True)),
                    totp_secret=user_data.get("totp_secret"),
                    totp_enabled=bool(user_data.get("totp_enabled", False)),
                )
            )
            summary["users_created"] += 1

    db.commit()
    refresh_guest_due_times(db)
    return summary


def parse_import_file(content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Import file must be UTF-8 JSON") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("Import file must contain a JSON object")
    return data
