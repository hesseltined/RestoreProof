"""
Purpose: Schedule helpers — due times, batch windows, coverage planning.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-28
Version: 1.2.0
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from croniter import croniter
from sqlalchemy.orm import Session

from app.models import Guest, ProxmoxHost, RestoreRun
from app.services.bootstrap import get_app_settings


def effective_cron(guest: Guest, global_cron: str) -> Optional[str]:
    if guest.excluded or not guest.schedule_enabled:
        return None
    if guest.schedule_cron:
        return guest.schedule_cron
    return global_cron


def compute_next_due(guest: Guest, global_cron: str, base: Optional[datetime] = None) -> Optional[datetime]:
    cron = effective_cron(guest, global_cron)
    if not cron:
        return None
    base = base or datetime.now(timezone.utc)
    try:
        itr = croniter(cron, base)
        nxt = itr.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt
    except (ValueError, KeyError):
        return None


def refresh_guest_due_times(db: Session) -> None:
    settings = get_app_settings(db)
    now = datetime.now(timezone.utc)
    for guest in db.query(Guest).all():
        guest.next_due_at = compute_next_due(guest, settings.global_cron, now)
    db.commit()


def schedule_window_start(cron: str, now: Optional[datetime] = None) -> datetime:
    """Start of the current schedule tick (previous cron fire time)."""
    now = now or datetime.now(timezone.utc)
    try:
        itr = croniter(cron, now)
        prev = itr.get_prev(datetime)
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        return prev
    except (ValueError, KeyError):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)


def estimate_ticks_per_period(cron: str, days: int = 7) -> float:
    """Approximate how many cron fires occur in `days` days."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    try:
        itr = croniter(cron, now)
        count = 0
        # Cap iterations for safety on very frequent crons
        for _ in range(10_000):
            nxt = itr.get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            if nxt > end:
                break
            count += 1
        return float(count) if count else 1.0
    except (ValueError, KeyError):
        return float(days)  # assume daily


def suggested_batch(eligible: int, ticks: float) -> int:
    if eligible <= 0:
        return 1
    ticks = max(ticks, 1.0)
    return max(1, int(math.ceil(eligible / ticks)))


def eligible_guests(db: Session) -> list[Guest]:
    return (
        db.query(Guest)
        .join(ProxmoxHost, Guest.host_id == ProxmoxHost.id)
        .filter(
            Guest.excluded.is_(False),
            Guest.schedule_enabled.is_(True),
            ProxmoxHost.enabled.is_(True),
        )
        .all()
    )


def enqueued_in_window(db: Session, window_start: datetime) -> int:
    return (
        db.query(RestoreRun)
        .filter(
            RestoreRun.trigger == "schedule",
            RestoreRun.created_at >= window_start,
        )
        .count()
    )


def guests_tested_in_window(db: Session, window_start: datetime) -> set[int]:
    rows = (
        db.query(RestoreRun.guest_id)
        .filter(
            RestoreRun.trigger == "schedule",
            RestoreRun.created_at >= window_start,
            RestoreRun.guest_id.isnot(None),
        )
        .all()
    )
    return {r[0] for r in rows if r[0] is not None}


def pick_next_guest(db: Session) -> Optional[Guest]:
    """Pick the most overdue eligible guest not already queued this schedule window."""
    settings = get_app_settings(db)
    if not settings.schedule_enabled:
        return None

    batch_size = max(1, int(settings.schedule_batch_size or 1))
    window_start = schedule_window_start(settings.global_cron)
    already = enqueued_in_window(db, window_start)
    if already >= batch_size:
        return None

    tested_ids = guests_tested_in_window(db, window_start)
    now = datetime.now(timezone.utc)
    candidates = eligible_guests(db)

    # Prefer guests not yet touched this window, oldest last_tested first
    pool = [g for g in candidates if g.id not in tested_ids]
    if not pool:
        return None

    # Soft due-check: if guest has a future next_due far away and was recently tested,
    # still allow rotation for batch coverage — coverage mode rotates the fleet.
    # Only skip guests that have a per-guest cron and are not yet due.
    due_pool: list[Guest] = []
    for g in pool:
        cron = effective_cron(g, settings.global_cron)
        if not cron:
            continue
        if g.schedule_cron:
            # Custom per-guest cron: respect due time
            if g.next_due_at and g.next_due_at > now:
                continue
            if g.next_due_at is None:
                base = g.last_tested_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
                nxt = compute_next_due(g, settings.global_cron, base)
                if nxt and nxt > now:
                    continue
        due_pool.append(g)

    if not due_pool:
        return None

    due_pool.sort(key=lambda g: g.last_tested_at or datetime(1970, 1, 1, tzinfo=timezone.utc))
    return due_pool[0]


def build_schedule_plan(db: Session) -> dict:
    settings = get_app_settings(db)
    total = db.query(Guest).count()
    excluded = db.query(Guest).filter(Guest.excluded.is_(True)).count()
    # Eligible = not excluded and schedule_enabled
    eligible = len(eligible_guests(db))
    cron = settings.global_cron or "0 2 * * *"
    batch = max(1, int(settings.schedule_batch_size or 1))
    goal = (settings.schedule_coverage_goal or "monthly").lower()

    ticks_week = estimate_ticks_per_period(cron, 7)
    ticks_month = estimate_ticks_per_period(cron, 30)
    sug_week = suggested_batch(eligible, ticks_week)
    sug_month = suggested_batch(eligible, ticks_month)

    ticks_to_cover = int(math.ceil(eligible / batch)) if eligible else 0
    # Estimate days: ticks_to_cover / (ticks per day)
    ticks_per_day = estimate_ticks_per_period(cron, 1) or 1.0
    days_estimate = ticks_to_cover / ticks_per_day if ticks_per_day else float(ticks_to_cover)

    cover_weekly = batch * ticks_week >= eligible if eligible else True
    cover_monthly = batch * ticks_month >= eligible if eligible else True

    window_start = schedule_window_start(cron)
    enqueued = enqueued_in_window(db, window_start)
    remaining = max(0, batch - enqueued)

    if eligible == 0:
        summary = "No eligible guests yet (sync inventory and un-exclude guests you want tested)."
    elif batch == 1 and ticks_per_day >= 0.9:
        summary = (
            f"Each schedule tick tests 1 guest. With {eligible} eligible guests, "
            f"a full cycle takes about {ticks_to_cover} nights (~{days_estimate:.0f} days)."
        )
    else:
        period = "week" if cover_weekly else ("month" if cover_monthly else "longer than a month")
        summary = (
            f"{batch} restore(s) per schedule tick × ~{ticks_week:.0f} ticks/week "
            f"covers ~{int(batch * ticks_week)} guests/week "
            f"({eligible} eligible). At this rate a full cycle fits in a {period}."
        )

    return {
        "total_guests": total,
        "excluded_count": excluded,
        "eligible_count": eligible,
        "schedule_batch_size": batch,
        "schedule_coverage_goal": goal,
        "global_cron": cron,
        "ticks_per_week": ticks_week,
        "ticks_per_month": ticks_month,
        "suggested_batch_weekly": sug_week,
        "suggested_batch_monthly": sug_month,
        "ticks_to_cover_all": ticks_to_cover,
        "days_to_cover_all_estimate": round(days_estimate, 1),
        "cover_weekly_ok": cover_weekly,
        "cover_monthly_ok": cover_monthly,
        "enqueued_this_window": enqueued,
        "window_remaining": remaining,
        "summary": summary,
    }
