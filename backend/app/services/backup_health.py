"""
Purpose: Decide whether a Proxmox backup is current, and whether its job is disabled.
Author: Doug Hesseltine
Created: 2026-10-19
Modified: 2026-10-19
Version: 1.0.0

A guest is current only when a covering vzdump job is enabled and the newest PBS
snapshot is inside that job's schedule (plus a short grace for a long run).
A disabled job is reported immediately, even when yesterday's snapshot is still
inside the window — turning backups off is how a stale copy gets left behind.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Weekly Sunday job plus the same grace used for a parsed "sun 01:00" schedule.
# Used when Proxmox sends a schedule string we cannot parse, so a silent
# "treat as current" cannot hide a stopped job.
_FALLBACK_SCHEDULE = "sun 01:00"
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\s*$")
_SUMMARY_SCHEDULE_RE = re.compile(r"\(([^)]+)\)")

BackupStatus = str  # current | disabled | stale | missing | unprotected


def schedule_max_gap(schedule: str) -> Optional[timedelta]:
    """Longest gap between runs of a Proxmox calendar schedule, or None if unknown."""
    raw = (schedule or "").strip().lower()
    if not raw:
        return None
    if raw in {"minutely"}:
        return timedelta(minutes=1)
    if raw in {"hourly"}:
        return timedelta(hours=1)
    if raw in {"daily"}:
        return timedelta(days=1)
    if raw in {"weekly"}:
        return timedelta(days=7)
    if raw in {"monthly"}:
        return timedelta(days=31)

    time_match = _TIME_RE.search(raw)
    body = raw[: time_match.start()].strip() if time_match else raw
    if not body:
        return timedelta(days=1)
    if body in {"hourly"}:
        return timedelta(hours=1)
    if body in {"daily", "*", "*-*-*"} or body.startswith("*-*-*"):
        return timedelta(days=1)

    days = _expand_weekdays(body)
    if not days:
        return None
    return _max_weekday_gap(days)


def freshness_limit(schedule: str) -> Optional[timedelta]:
    """How old the newest snapshot may be and still count as current."""
    gap = schedule_max_gap(schedule)
    if gap is None:
        return None
    grace = min(timedelta(hours=36), max(timedelta(hours=2), gap * 0.25))
    return gap + grace


def strictest_schedule(jobs: list[dict]) -> str:
    """Schedule with the shortest gap. Enabled jobs should be passed first."""
    best = ""
    best_gap: Optional[timedelta] = None
    for job in jobs:
        schedule = str(job.get("schedule") or "").strip()
        if not schedule:
            continue
        gap = schedule_max_gap(schedule)
        if gap is None:
            if not best:
                best = schedule
            continue
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = schedule
    return best


def apply_job_coverage(guest: Any, jobs: list[dict]) -> None:
    """Write enabled flag and the schedule used for the freshness check."""
    enabled: list[dict] = []
    disabled: list[dict] = []
    for job in jobs:
        flag = job.get("enabled", 1)
        is_enabled = flag not in (0, False, "0", "false", "False")
        (enabled if is_enabled else disabled).append(job)
    guest.backup_job_enabled = bool(enabled)
    guest.backup_schedule = strictest_schedule(enabled or disabled)


def guest_schedule(guest: Any) -> str:
    stored = str(getattr(guest, "backup_schedule", None) or "").strip()
    if stored:
        return stored
    summary = str(getattr(guest, "backup_job_summary", None) or "")
    match = _SUMMARY_SCHEDULE_RE.search(summary)
    return match.group(1).strip() if match else ""


def assess_backup(guest: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """
    Return status, schedule, and a sentence Doug can act on.

    ``disabled`` wins over ``stale``: a job that is off is the problem even
    when the last snapshot is still young.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if not bool(getattr(guest, "in_backup_job", False)):
        return _result(
            "unprotected",
            "",
            None,
            None,
            "Not listed in any Proxmox backup job (Datacenter → Backup).",
        )

    schedule = guest_schedule(guest)
    recognized = freshness_limit(schedule) is not None if schedule else False
    limit = freshness_limit(schedule) if recognized else freshness_limit(_FALLBACK_SCHEDULE)
    last = _aware(getattr(guest, "last_backup_at", None))
    age = (now - last) if last is not None else None
    enabled = bool(getattr(guest, "backup_job_enabled", False))
    schedule_label = schedule or "unrecognized schedule"

    if not enabled:
        if last is None:
            detail = (
                f"Backup job is disabled ({schedule_label}). No PBS snapshot exists."
            )
        else:
            detail = (
                f"Backup job is disabled ({schedule_label}). "
                f"Last snapshot {_fmt(last)} ({_age_phrase(age)} ago)."
            )
        return _result("disabled", schedule, limit, age, detail)

    if last is None or int(getattr(guest, "backup_snapshot_count", 0) or 0) <= 0:
        shown = schedule or "its backup job"
        return _result(
            "missing",
            schedule,
            limit,
            None,
            f"No PBS backup exists yet. It is scheduled by {shown} but has not "
            "produced a snapshot — run that backup job first.",
        )

    assert limit is not None
    assert age is not None
    if age > limit:
        if recognized:
            why = f"The job schedule is {schedule}."
        else:
            why = "The schedule was not recognized, so the weekly limit is used."
        return _result(
            "stale",
            schedule,
            limit,
            age,
            f"Newest snapshot is {_fmt(last)} ({_age_phrase(age)} ago). {why} "
            f"A current backup has to be newer than {_age_phrase(limit)}.",
        )

    return _result(
        "current",
        schedule,
        limit,
        age,
        f"Newest snapshot {_fmt(last)} is inside the {schedule_label} window.",
    )


def fleet_backup_report(
    guests: list[Any],
    now: Optional[datetime] = None,
    *,
    list_limit: int = 12,
) -> dict[str, Any]:
    """Roll up non-excluded guests. Excluded guests are intentionally omitted."""
    disabled: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    current = 0
    for guest in guests:
        if bool(getattr(guest, "excluded", False)):
            continue
        assessed = assess_backup(guest, now)
        status = assessed["status"]
        if status == "current":
            current += 1
            continue
        if status == "unprotected":
            continue
        row = {
            "vmid": int(getattr(guest, "vmid", 0) or 0),
            "name": str(getattr(guest, "name", "") or ""),
            "last_backup_at": _aware(getattr(guest, "last_backup_at", None)),
            "detail": assessed["detail"],
            "job_label": str(getattr(guest, "backup_job_summary", "") or "") or "Backup job",
        }
        if status == "disabled":
            disabled.append(row)
        elif status == "stale":
            stale.append(row)
        elif status == "missing":
            missing.append(row)

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in disabled:
        groups.setdefault(row["job_label"], []).append(row)
    disabled_jobs = []
    for label, rows in sorted(groups.items()):
        dates = [r["last_backup_at"] for r in rows if r["last_backup_at"] is not None]
        disabled_jobs.append(
            {
                "label": label,
                "guest_count": len(rows),
                "oldest_backup_at": min(dates) if dates else None,
            }
        )

    stale_sorted = sorted(
        stale, key=lambda r: r["last_backup_at"] or datetime.min.replace(tzinfo=timezone.utc)
    )
    missing_sorted = sorted(missing, key=lambda r: (r["name"], r["vmid"]))
    fingerprint = "|".join(
        [f"d:{job['label']}" for job in disabled_jobs]
        + [f"s:{row['vmid']}" for row in stale_sorted]
        + [f"m:{row['vmid']}" for row in missing_sorted]
    )
    ok = not disabled and not stale and not missing
    report = {
        "ok": ok,
        "headline": _headline(disabled_jobs, len(stale), len(missing)),
        "current_count": current,
        "disabled_count": len(disabled),
        "stale_count": len(stale),
        "missing_count": len(missing),
        "disabled_jobs": disabled_jobs,
        "stale_guests": [_public_guest(r) for r in stale_sorted[:list_limit]],
        "missing_guests": [_public_guest(r) for r in missing_sorted[:list_limit]],
        "fingerprint": fingerprint,
    }
    return report


def alert_is_due(
    fingerprint: str,
    *,
    last_fingerprint: str,
    last_sent_at: Optional[datetime],
    now: datetime,
    repeat_after: timedelta = timedelta(hours=24),
) -> bool:
    """True when this problem set has not been sent, or the daily repeat is due."""
    if not fingerprint:
        return False
    if fingerprint != (last_fingerprint or ""):
        return True
    if last_sent_at is None:
        return True
    sent = _aware(last_sent_at)
    if sent is None:
        return True
    return now - sent >= repeat_after


def _headline(disabled_jobs: list[dict[str, Any]], stale: int, missing: int) -> str:
    if disabled_jobs:
        labels = ", ".join(job["label"] for job in disabled_jobs[:3])
        guests = sum(int(job["guest_count"]) for job in disabled_jobs)
        noun = "guest is" if guests == 1 else "guests are"
        return f"{guests} {noun} on a disabled backup job: {labels}."
    if stale:
        noun = "guest has" if stale == 1 else "guests have"
        return f"{stale} {noun} a backup older than the job schedule."
    if missing:
        noun = "guest is" if missing == 1 else "guests are"
        return f"{missing} {noun} in a backup job with no PBS snapshot yet."
    return "Backups are current."


def _public_guest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vmid": row["vmid"],
        "name": row["name"],
        "last_backup_at": row["last_backup_at"],
        "detail": row["detail"],
    }


def _result(
    status: str,
    schedule: str,
    limit: Optional[timedelta],
    age: Optional[timedelta],
    detail: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "schedule": schedule,
        "limit": limit,
        "age": age,
        "detail": detail,
    }


def _expand_weekdays(body: str) -> Optional[set[int]]:
    days: set[int] = set()
    for part in re.split(r"[\s,]+", body.strip()):
        if not part:
            continue
        if ".." in part:
            start, end = part.split("..", 1)
            if start not in _WEEKDAYS or end not in _WEEKDAYS:
                return None
            ia = _WEEKDAYS.index(start)
            ib = _WEEKDAYS.index(end)
            if ia <= ib:
                days.update(range(ia, ib + 1))
            else:
                days.update(range(ia, 7))
                days.update(range(0, ib + 1))
            continue
        if part not in _WEEKDAYS:
            return None
        days.add(_WEEKDAYS.index(part))
    return days


def _max_weekday_gap(days: set[int]) -> timedelta:
    if len(days) >= 7:
        return timedelta(days=1)
    ordered = sorted(days)
    gaps: list[int] = []
    for index, day in enumerate(ordered):
        nxt = ordered[(index + 1) % len(ordered)]
        gap = (nxt - day) % 7
        if gap == 0:
            gap = 7
        gaps.append(gap)
    return timedelta(days=max(gaps))


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _fmt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")


def _age_phrase(delta: Optional[timedelta]) -> str:
    if delta is None:
        return "an unknown time"
    seconds = max(0, int(delta.total_seconds()))
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    if days >= 2:
        return f"{days} days"
    if days == 1:
        return "1 day"
    if hours >= 2:
        return f"{hours} hours"
    minutes = max(1, seconds // 60)
    return f"{minutes} minutes"
