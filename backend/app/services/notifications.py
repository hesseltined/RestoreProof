"""
Purpose: Nightly restore digests, schedule-gap alerts, and new-guest backup nudges.
Author: Doug Hesseltine
Created: 2026-09-15
Modified: 2026-10-01
Version: 1.2.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Guest, ProxmoxHost, RestoreRun
from app.services.bootstrap import get_app_settings, get_push_settings, public_app_url
from app.services.email_templates import (
    build_digest_email,
    build_gap_alert_email,
    build_unbacked_nudge_email,
    format_timestamp,
)
from app.services.mailer import parse_addr_list, send_email
from app.services.pusher import build_digest_push, build_gap_push, send_push
from app.services.scheduler import eligible_guests, pick_next_guest, schedule_window_start

logger = logging.getLogger(__name__)

DIGEST_WAIT = timedelta(minutes=15)
GAP_HOURS_MIN = 1
GAP_HOURS_MAX = 168


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _append_log(run: RestoreRun, line: str) -> None:
    stamp = _now().strftime("%H:%M:%S")
    run.log_text = (run.log_text or "") + f"[{stamp}] {line}\n"


def pending_schedule_runs(db: Session) -> list[RestoreRun]:
    return (
        db.query(RestoreRun)
        .filter(
            RestoreRun.trigger == "schedule",
            RestoreRun.status.in_(("success", "failed")),
            RestoreRun.notified_at.is_(None),
        )
        .order_by(RestoreRun.id.asc())
        .all()
    )


def schedule_digest_should_wait(
    db: Session,
    *,
    now: Optional[datetime] = None,
    wait_for: timedelta = DIGEST_WAIT,
) -> bool:
    """True when more scheduled restores are still coming tonight."""
    busy = (
        db.query(RestoreRun)
        .filter(
            RestoreRun.trigger == "schedule",
            RestoreRun.status.in_(("queued", "running")),
        )
        .first()
    )
    if busy:
        return True
    pending = pending_schedule_runs(db)
    if not pending:
        return False
    newest = max((_aware(r.finished_at) or _aware(r.created_at) or _now()) for r in pending)
    now = now or _now()
    if now - newest >= wait_for:
        return False
    settings = get_app_settings(db)
    if not settings.schedule_enabled:
        return False
    return pick_next_guest(db) is not None


def _wants(status: str, *, on_success: bool, on_failure: bool) -> bool:
    if status == "success":
        return on_success
    if status == "failed":
        return on_failure
    return False


async def _email_digest(
    db: Session,
    runs: list[RestoreRun],
    *,
    app_url: str,
) -> None:
    settings = get_app_settings(db)
    wanted = [
        run
        for run in runs
        if _wants(
            run.status,
            on_success=settings.notify_on_success,
            on_failure=settings.notify_on_failure,
        )
    ]
    if not wanted:
        return
    to_addrs = parse_addr_list(settings.notify_to)
    if not to_addrs:
        return
    subject, body = build_digest_email(wanted, app_url)
    await send_email(
        db,
        to_addrs=to_addrs,
        subject=subject,
        body=body,
        cc_addrs=parse_addr_list(settings.notify_cc),
    )


async def _push_digest(
    db: Session,
    runs: list[RestoreRun],
    *,
    failed: bool,
    app_url: str,
) -> None:
    push = get_push_settings(db)
    if not push.enabled or not push.url.strip():
        return
    if not _wants(
        "failed" if failed else "success",
        on_success=push.on_success,
        on_failure=push.on_failure,
    ):
        return
    payload = build_digest_push(runs, failed=failed, click_url=app_url.rstrip("/"))
    await send_push(db, **payload)


async def send_schedule_digests(db: Session) -> int:
    """Send one nightly restore report (pass and fail together), then mark those runs notified."""
    pending = pending_schedule_runs(db)
    if not pending:
        return 0
    app_url = public_app_url(get_app_settings(db))
    successes = [r for r in pending if r.status == "success"]
    failures = [r for r in pending if r.status == "failed"]
    now = _now()
    try:
        await _email_digest(db, pending, app_url=app_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("restore digest email failed")
        for run in pending:
            _append_log(run, f"Restore digest email failed: {exc}")
    else:
        for run in pending:
            _append_log(run, "Included in nightly restore digest")
    if successes:
        try:
            await _push_digest(db, successes, failed=False, app_url=app_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("success digest push failed")
            for run in successes:
                _append_log(run, f"Success digest push failed: {exc}")
    if failures:
        try:
            await _push_digest(db, failures, failed=True, app_url=app_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failure digest push failed")
            for run in failures:
                _append_log(run, f"Failure digest push failed: {exc}")
    for run in pending:
        run.notified_at = now
    db.commit()
    return len(pending)


async def flush_schedule_digests(db: Session, *, now: Optional[datetime] = None) -> int:
    """Send deferred nightly reports when the tick is done or has been sitting too long."""
    if not pending_schedule_runs(db):
        return 0
    if schedule_digest_should_wait(db, now=now):
        return 0
    return await send_schedule_digests(db)


def evaluate_gap(db: Session, *, now: Optional[datetime] = None) -> Optional[dict]:
    """
    Return alert payload when the schedule is on and no restore finished recently.

    None means do not alert (disabled, schedule off, or last restore is still fresh).
    """
    settings = get_app_settings(db)
    if not settings.schedule_enabled or not getattr(settings, "gap_alert_enabled", True):
        return None
    hours = max(GAP_HOURS_MIN, min(GAP_HOURS_MAX, int(settings.gap_alert_hours or 26)))
    threshold = timedelta(hours=hours)
    now = now or _now()
    last = (
        db.query(RestoreRun)
        .filter(
            RestoreRun.status.in_(("success", "failed")),
            RestoreRun.finished_at.isnot(None),
        )
        .order_by(RestoreRun.finished_at.desc())
        .first()
    )
    eligible = len(eligible_guests(db))
    no_snapshot = (
        db.query(Guest)
        .filter(
            Guest.excluded.is_(False),
            Guest.in_backup_job.is_(True),
            Guest.backup_snapshot_count == 0,
        )
        .count()
    )
    disabled_job = (
        db.query(Guest)
        .filter(
            Guest.excluded.is_(False),
            Guest.backup_job_summary.ilike("%[disabled]%"),
        )
        .count()
    )
    last_finished = _aware(last.finished_at) if last else None
    if last_finished is not None:
        age = now - last_finished
        if age < threshold:
            return None
        hours_since = age.total_seconds() / 3600.0
    else:
        if eligible > 0:
            # First tick has not run yet; do not nag a brand-new schedule.
            return None
        hours_since = None

    last_sent = _aware(getattr(settings, "gap_alert_last_sent_at", None))
    if last_sent is not None and now - last_sent < threshold:
        return None

    return {
        "hours_since": hours_since,
        "last_guest": last.source_name if last else None,
        "last_finished": format_timestamp(last_finished) if last_finished else "never",
        "eligible": eligible,
        "no_snapshot": no_snapshot,
        "disabled_job": disabled_job,
    }


async def _deliver_gap(db: Session, payload: dict) -> bool:
    settings = get_app_settings(db)
    app_url = public_app_url(settings)
    delivered = False
    to_addrs = parse_addr_list(settings.notify_to)
    if to_addrs:
        try:
            subject, body = build_gap_alert_email(payload, app_url)
            await send_email(
                db,
                to_addrs=to_addrs,
                subject=subject,
                body=body,
                cc_addrs=parse_addr_list(settings.notify_cc),
            )
            delivered = True
        except Exception:  # noqa: BLE001
            logger.exception("Gap alert email failed")
    push = get_push_settings(db)
    if push.enabled and push.url.strip():
        try:
            await send_push(db, **build_gap_push(payload, app_url))
            delivered = True
        except Exception:  # noqa: BLE001
            logger.exception("Gap alert push failed")
    return delivered


async def maybe_send_gap_alert(db: Session, *, now: Optional[datetime] = None) -> bool:
    payload = evaluate_gap(db, now=now)
    if not payload:
        return False
    delivered = await _deliver_gap(db, payload)
    settings = get_app_settings(db)
    settings.gap_alert_last_sent_at = now or _now()
    db.commit()
    if delivered:
        logger.warning(
            "Gap alert sent: last=%s eligible=%s hours=%.1f",
            payload.get("last_guest"),
            payload.get("eligible"),
            payload.get("hours_since") or -1,
        )
    else:
        logger.warning(
            "Gap alert due but no email/push delivered (check SMTP and ntfy settings)"
        )
    return delivered


def pending_unbacked_guests(db: Session) -> list[Guest]:
    """Guests first seen without a backup job that have not been emailed yet."""
    return (
        db.query(Guest)
        .filter(
            Guest.backup_nudge_sent_at.is_(None),
            Guest.in_backup_job.is_(False),
            Guest.excluded.is_(False),
        )
        .order_by(Guest.host_id.asc(), Guest.vmid.asc())
        .all()
    )


def _hosts_synced_this_window(db: Session, window_start: datetime) -> bool:
    hosts = (
        db.query(ProxmoxHost)
        .filter(ProxmoxHost.enabled.is_(True))
        .order_by(ProxmoxHost.id.asc())
        .all()
    )
    if not hosts:
        return False
    for host in hosts:
        synced = _aware(host.last_sync_at)
        if synced is None or synced < window_start:
            return False
    return True


async def _deliver_unbacked_nudge(db: Session, guests: list[Guest]) -> bool:
    settings = get_app_settings(db)
    to_addrs = parse_addr_list(settings.notify_to)
    if not to_addrs:
        logger.warning("Unbacked-guest email skipped: no notification recipients")
        return False
    app_url = public_app_url(settings)
    subject, body = build_unbacked_nudge_email(guests, app_url)
    try:
        await send_email(
            db,
            to_addrs=to_addrs,
            subject=subject,
            body=body,
            cc_addrs=parse_addr_list(settings.notify_cc),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Unbacked-guest email failed")
        return False
    return True


async def maybe_send_unbacked_nudge(db: Session, *, now: Optional[datetime] = None) -> bool:
    """
    Once per schedule window, email guests first seen with no backup job.

    Existing guests are stamped at upgrade time and are never included.
    A guest is stamped after a successful send, so later windows stay quiet.
    """
    settings = get_app_settings(db)
    if not getattr(settings, "unbacked_nudge_enabled", True):
        return False
    if not settings.schedule_enabled:
        return False
    now = now or _now()
    window = schedule_window_start(settings.global_cron or "0 2 * * *", now)
    last_sent = _aware(getattr(settings, "unbacked_nudge_last_sent_at", None))
    if last_sent is not None and last_sent >= window:
        return False
    if not _hosts_synced_this_window(db, window):
        return False

    pending = pending_unbacked_guests(db)
    delivered = False
    if pending:
        delivered = await _deliver_unbacked_nudge(db, pending)
        if delivered:
            for guest in pending:
                guest.backup_nudge_sent_at = now
            logger.info(
                "Unbacked-guest email sent for %s guest(s)",
                len(pending),
            )
        else:
            logger.warning(
                "Unbacked-guest email due for %s guest(s) but not delivered",
                len(pending),
            )
    settings.unbacked_nudge_last_sent_at = now
    db.commit()
    return delivered
