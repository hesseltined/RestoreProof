"""
Purpose: Unit tests for nightly restore digests and schedule-gap alerts.
Author: Doug Hesseltine
Created: 2026-09-15
Modified: 2026-09-17
Version: 1.1.0
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.bootstrap import public_app_url
from app.services.email_templates import build_digest_email
from app.services.notifications import (
    evaluate_gap,
    schedule_digest_should_wait,
    send_schedule_digests,
)
from app.services.restore import notify_run

NOW = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)


def _settings(**kw) -> SimpleNamespace:
    base = {
        "schedule_enabled": True,
        "gap_alert_enabled": True,
        "gap_alert_hours": 26,
        "gap_alert_last_sent_at": None,
        "notify_on_success": True,
        "notify_on_failure": True,
        "notify_to": "ops@example.com",
        "notify_cc": "",
        "public_base_url": "",
        "email_success_subject": "ok {{guest_name}}",
        "email_success_body": "{{guest_name}}",
        "email_failure_subject": "bad {{guest_name}}",
        "email_failure_body": "{{error_message}}",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _run(**kw) -> SimpleNamespace:
    base = {
        "id": 1,
        "status": "success",
        "trigger": "schedule",
        "log_text": "",
        "notified_at": None,
        "source_name": "immich",
        "source_vmid": 133,
        "guest_type": "lxc",
        "test_vmid": 9001,
        "backup_volid": "pbs:backup/ct/133/x",
        "backup_count": 1,
        "backup_used_index": 1,
        "latest_backup_volid": "",
        "used_fallback_backup": False,
        "result_summary": "ok",
        "error_message": "",
        "started_at": NOW - timedelta(minutes=5),
        "finished_at": NOW - timedelta(minutes=1),
        "created_at": NOW - timedelta(minutes=5),
        "evidence_kind": "none",
        "evidence_path": None,
        "evidence_json": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _db_for_digest(*, busy=None, pending=None) -> MagicMock:
    db = MagicMock()
    filt = db.query.return_value.filter.return_value
    filt.first.return_value = busy
    filt.order_by.return_value.all.return_value = pending or []
    return db


def test_skipped_run_sends_no_notification() -> None:
    run = _run(status="skipped", trigger="schedule")
    db = MagicMock()
    with patch("app.services.restore.send_email") as send:
        asyncio.run(notify_run(db, run))
    send.assert_not_called()
    assert run.notified_at is not None


def test_scheduled_run_defers_when_more_are_coming() -> None:
    run = _run()
    db = MagicMock()
    with patch("app.services.restore.schedule_digest_should_wait", return_value=True), patch(
        "app.services.restore.send_email"
    ) as send:
        asyncio.run(notify_run(db, run))
    send.assert_not_called()
    assert run.notified_at is None
    assert "held until" in run.log_text


def test_scheduled_run_flushes_digest_when_tick_is_done() -> None:
    run = _run()
    db = MagicMock()
    with patch("app.services.restore.schedule_digest_should_wait", return_value=False), patch(
        "app.services.restore.send_schedule_digests", new_callable=AsyncMock
    ) as digest, patch("app.services.restore.send_email") as send:
        asyncio.run(notify_run(db, run))
    digest.assert_awaited_once()
    send.assert_not_called()


def test_manual_run_mails_immediately() -> None:
    run = _run(trigger="manual")
    db = MagicMock()
    with patch("app.services.restore.get_app_settings", return_value=_settings()), patch(
        "app.services.restore.get_push_settings",
        return_value=SimpleNamespace(enabled=False, url=""),
    ), patch(
        "app.services.restore.public_app_url",
        return_value="https://rp.example",
    ), patch("app.services.restore.send_email", new_callable=AsyncMock) as send:
        asyncio.run(notify_run(db, run))
    send.assert_awaited_once()
    assert run.notified_at is not None


def test_resend_force_bypasses_digest_hold() -> None:
    run = _run()
    db = MagicMock()
    with patch("app.services.restore.schedule_digest_should_wait", return_value=True), patch(
        "app.services.restore.get_app_settings", return_value=_settings()
    ), patch(
        "app.services.restore.get_push_settings",
        return_value=SimpleNamespace(enabled=False, url=""),
    ), patch(
        "app.services.restore.public_app_url",
        return_value="https://rp.example",
    ), patch("app.services.restore.send_email", new_callable=AsyncMock) as send:
        asyncio.run(notify_run(db, run, force=True))
    send.assert_awaited_once()
    assert run.notified_at is not None


def test_wait_when_another_scheduled_run_is_queued() -> None:
    db = _db_for_digest(busy=_run(status="queued"), pending=[])
    assert schedule_digest_should_wait(db, now=NOW) is True


def test_no_wait_when_queue_is_idle_and_nothing_pending() -> None:
    db = _db_for_digest(busy=None, pending=[])
    assert schedule_digest_should_wait(db, now=NOW) is False


def test_wait_when_next_guest_is_due_and_last_finish_is_fresh() -> None:
    pending = [_run(finished_at=NOW - timedelta(minutes=1))]
    db = _db_for_digest(busy=None, pending=pending)
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch("app.services.notifications.pick_next_guest", return_value=object()):
        assert schedule_digest_should_wait(db, now=NOW) is True


def test_flush_when_held_runs_are_older_than_wait_window() -> None:
    pending = [_run(finished_at=NOW - timedelta(minutes=16))]
    db = _db_for_digest(busy=None, pending=pending)
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch("app.services.notifications.pick_next_guest", return_value=object()):
        assert schedule_digest_should_wait(db, now=NOW) is False


def test_digest_sends_one_email_with_pass_and_fail() -> None:
    ok = _run(id=1, status="success", source_name="jellyfin")
    bad = _run(id=2, status="failed", source_name="matomo", error_message="boom")
    db = _db_for_digest(pending=[ok, bad])
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch(
        "app.services.notifications.get_push_settings",
        return_value=SimpleNamespace(enabled=False, url=""),
    ), patch(
        "app.services.notifications.public_app_url",
        return_value="https://rp.example",
    ), patch("app.services.notifications.send_email", new_callable=AsyncMock) as send:
        asyncio.run(send_schedule_digests(db))
    assert send.await_count == 1
    subject = send.await_args.kwargs["subject"]
    body = send.await_args.kwargs["body"]
    assert "passed" in subject
    assert "failed" in subject
    assert "PASSED" in body
    assert "FAILED" in body
    assert "#16a34a" in body
    assert "#dc2626" in body
    assert "https://rp.example/runs/1" in body
    assert "https://rp.example/runs/2" in body
    assert "localhost" not in body
    assert ok.notified_at is not None
    assert bad.notified_at is not None


def test_public_app_url_prefers_saved_setting() -> None:
    row = SimpleNamespace(public_base_url=" https://restoreproof.technologist.services/ ")
    with patch(
        "app.services.bootstrap.get_settings",
        return_value=SimpleNamespace(app_base_url="http://localhost:3080"),
    ):
        assert public_app_url(row) == "https://restoreproof.technologist.services"


def test_public_app_url_falls_back_to_env() -> None:
    row = SimpleNamespace(public_base_url="  ")
    with patch(
        "app.services.bootstrap.get_settings",
        return_value=SimpleNamespace(app_base_url="https://rp.example"),
    ):
        assert public_app_url(row) == "https://rp.example"


def test_digest_html_open_links_use_live_url() -> None:
    ok = _run(id=331, status="success", source_name="immich")
    bad = _run(id=332, status="failed", source_name="matomo", error_message="401")
    subject, body = build_digest_email(
        [ok, bad], "https://restoreproof.technologist.services"
    )
    assert "https://restoreproof.technologist.services/runs/331" in body
    assert "https://restoreproof.technologist.services/runs/332" in body
    assert "localhost" not in body
    assert "PASSED" in body
    assert "FAILED" in body
    assert "1 passed" in body
    assert "1 failed" in body
    assert subject == "RestoreProof: 1 passed, 1 failed"


def _gap_db(last) -> MagicMock:
    db = MagicMock()
    filt = db.query.return_value.filter.return_value
    filt.order_by.return_value.first.return_value = last
    filt.count.return_value = 3
    return db


def test_gap_alert_when_last_restore_is_stale() -> None:
    last = _run(finished_at=NOW - timedelta(hours=40), source_name="matomo")
    db = _gap_db(last)
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch("app.services.notifications.eligible_guests", return_value=[]):
        payload = evaluate_gap(db, now=NOW)
    assert payload is not None
    assert payload["last_guest"] == "matomo"
    assert payload["hours_since"] == 40
    assert payload["eligible"] == 0


def test_no_gap_alert_when_a_restore_finished_recently() -> None:
    last = _run(finished_at=NOW - timedelta(hours=2))
    db = _gap_db(last)
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch("app.services.notifications.eligible_guests", return_value=[object()]):
        assert evaluate_gap(db, now=NOW) is None


def test_gap_alert_respects_cooldown() -> None:
    last = _run(finished_at=NOW - timedelta(hours=40))
    db = _gap_db(last)
    settings = _settings(gap_alert_last_sent_at=NOW - timedelta(hours=3))
    with patch("app.services.notifications.get_app_settings", return_value=settings), patch(
        "app.services.notifications.eligible_guests", return_value=[]
    ):
        assert evaluate_gap(db, now=NOW) is None


def test_no_gap_when_schedule_disabled() -> None:
    last = _run(finished_at=NOW - timedelta(hours=40))
    db = _gap_db(last)
    with patch(
        "app.services.notifications.get_app_settings",
        return_value=_settings(schedule_enabled=False),
    ), patch("app.services.notifications.eligible_guests", return_value=[]):
        assert evaluate_gap(db, now=NOW) is None


def test_new_schedule_with_eligible_guests_is_not_a_gap() -> None:
    db = _gap_db(None)
    with patch(
        "app.services.notifications.get_app_settings", return_value=_settings()
    ), patch("app.services.notifications.eligible_guests", return_value=[object()]):
        assert evaluate_gap(db, now=NOW) is None
