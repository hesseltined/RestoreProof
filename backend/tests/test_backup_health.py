"""
Purpose: Backup currency and disabled-job detection.
Author: Doug Hesseltine
Created: 2026-10-19
Modified: 2026-10-19
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.backup_health import (
    alert_is_due,
    apply_job_coverage,
    assess_backup,
    fleet_backup_report,
    freshness_limit,
    schedule_max_gap,
)

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
WEEKLY = {"id": "backup-weekly", "enabled": 1, "schedule": "sun 01:00"}
WEEKLY_OFF = {"id": "backup-weekly", "enabled": 0, "schedule": "sun 01:00"}


def _guest(**kwargs: object) -> SimpleNamespace:
    base = dict(
        vmid=122,
        name="DC1",
        excluded=False,
        in_backup_job=True,
        backup_job_enabled=True,
        backup_job_summary="backup-weekly (sun 01:00)",
        backup_schedule="sun 01:00",
        backup_snapshot_count=2,
        last_backup_at=NOW - timedelta(days=2),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_sunday_schedule_is_weekly() -> None:
    assert schedule_max_gap("sun 01:00") == timedelta(days=7)
    limit = freshness_limit("sun 01:00")
    assert limit is not None
    assert limit == timedelta(days=7, hours=36)


def test_weekday_range_uses_the_longest_gap() -> None:
    assert schedule_max_gap("mon..fri 21:00") == timedelta(days=3)
    assert schedule_max_gap("21:00") == timedelta(days=1)
    assert schedule_max_gap("hourly") == timedelta(hours=1)


def test_enabled_job_with_a_recent_snapshot_is_current() -> None:
    assessed = assess_backup(_guest(), NOW)
    assert assessed["status"] == "current"


def test_disabled_job_is_flagged_even_when_the_snapshot_is_recent() -> None:
    guest = _guest(
        backup_job_enabled=False,
        backup_job_summary="backup-weekly (sun 01:00) [disabled]",
        last_backup_at=NOW - timedelta(days=1),
    )
    assessed = assess_backup(guest, NOW)
    assert assessed["status"] == "disabled"
    assert "disabled" in assessed["detail"]


def test_disabled_job_reads_schedule_from_the_summary_when_unset() -> None:
    guest = _guest(
        backup_job_enabled=False,
        backup_schedule="",
        backup_job_summary="backup-2ab3984b-b8fb (sun 01:00) [disabled]",
        last_backup_at=NOW - timedelta(days=90),
    )
    assessed = assess_backup(guest, NOW)
    assert assessed["status"] == "disabled"
    assert "90 days" in assessed["detail"] or "91 days" in assessed["detail"]


def test_enabled_job_with_a_july_snapshot_is_stale() -> None:
    guest = _guest(last_backup_at=datetime(2026, 7, 20, 15, 42, tzinfo=timezone.utc))
    assessed = assess_backup(guest, NOW)
    assert assessed["status"] == "stale"


def test_apply_job_coverage_keeps_the_enabled_schedule() -> None:
    guest = _guest(backup_job_enabled=False, backup_schedule="")
    apply_job_coverage(guest, [WEEKLY_OFF, {**WEEKLY, "schedule": "daily"}])
    assert guest.backup_job_enabled is True
    assert guest.backup_schedule == "daily"


def test_apply_job_coverage_records_a_disabled_schedule() -> None:
    guest = _guest()
    apply_job_coverage(guest, [WEEKLY_OFF])
    assert guest.backup_job_enabled is False
    assert guest.backup_schedule == "sun 01:00"


def test_fleet_report_groups_one_disabled_job() -> None:
    guests = [
        _guest(vmid=122, name="DC1", backup_job_enabled=False),
        _guest(vmid=117, name="Win11Pro", backup_job_enabled=False),
        _guest(vmid=140, name="other", in_backup_job=False, backup_snapshot_count=0, last_backup_at=None),
        _guest(vmid=100, name="excluded", excluded=True, backup_job_enabled=False),
    ]
    report = fleet_backup_report(guests, NOW)
    assert report["ok"] is False
    assert report["disabled_count"] == 2
    assert report["current_count"] == 0
    assert report["disabled_jobs"][0]["guest_count"] == 2
    assert "disabled" in report["headline"]


def test_alert_repeats_daily_and_fires_immediately_on_a_new_problem() -> None:
    assert alert_is_due("d:job", last_fingerprint="", last_sent_at=None, now=NOW)
    assert not alert_is_due(
        "d:job",
        last_fingerprint="d:job",
        last_sent_at=NOW - timedelta(hours=2),
        now=NOW,
    )
    assert alert_is_due(
        "d:job",
        last_fingerprint="d:job",
        last_sent_at=NOW - timedelta(hours=25),
        now=NOW,
    )
    assert alert_is_due(
        "d:job|s:117",
        last_fingerprint="d:job",
        last_sent_at=NOW - timedelta(hours=1),
        now=NOW,
    )
