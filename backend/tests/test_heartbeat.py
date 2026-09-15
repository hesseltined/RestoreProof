"""
Purpose: Unit tests for the worker heartbeat (dead-man's-switch) ping.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.heartbeat import (
    HeartbeatConfigError,
    due_for_ping,
    maybe_send_heartbeat,
    validate_url,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _cfg(**kw) -> SimpleNamespace:
    base = {
        "enabled": True,
        "url": "http://uptime-kuma:3001/api/push/AbC123",
        "interval_seconds": 300,
        "verify_ssl": True,
        "last_ping_at": None,
        "last_error": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "url",
    [
        "http://uptime-kuma:3001/api/push/AbC123",
        "https://hc-ping.com/abcd-1234",
        "https://uptime.example.com/api/push/x?status=up&msg=OK",
    ],
)
def test_accepts_common_monitor_urls(url: str) -> None:
    assert validate_url(url) == url


@pytest.mark.parametrize("bad", ["", "   ", "uptime-kuma:3001/push", "ftp://x/y", "/api/push/x"])
def test_rejects_unusable_urls(bad: str) -> None:
    with pytest.raises(HeartbeatConfigError):
        validate_url(bad)


def test_never_pinged_is_due_immediately() -> None:
    assert due_for_ping(_cfg(), NOW) is True


def test_not_due_before_the_interval_elapses() -> None:
    cfg = _cfg(last_ping_at=NOW - timedelta(seconds=120))
    assert due_for_ping(cfg, NOW) is False


def test_due_once_the_interval_elapses() -> None:
    cfg = _cfg(last_ping_at=NOW - timedelta(seconds=301))
    assert due_for_ping(cfg, NOW) is True


def test_naive_timestamps_are_treated_as_utc() -> None:
    cfg = _cfg(last_ping_at=(NOW - timedelta(seconds=120)).replace(tzinfo=None))
    assert due_for_ping(cfg, NOW) is False


def test_disabled_or_urlless_config_never_pings() -> None:
    assert due_for_ping(_cfg(enabled=False), NOW) is False
    assert due_for_ping(_cfg(url="  "), NOW) is False


def test_successful_ping_records_time_and_clears_error() -> None:
    cfg = _cfg(last_error="previous failure")
    db = MagicMock()
    with patch("app.services.heartbeat.get_heartbeat_settings", return_value=cfg), patch(
        "app.services.heartbeat.send_heartbeat"
    ) as send:
        assert maybe_send_heartbeat(db) is True
        send.assert_called_once()
    assert cfg.last_ping_at is not None
    assert cfg.last_error == ""


def test_failed_ping_is_recorded_but_never_raises() -> None:
    """A monitoring outage must not take down the worker loop."""
    cfg = _cfg()
    db = MagicMock()
    with patch("app.services.heartbeat.get_heartbeat_settings", return_value=cfg), patch(
        "app.services.heartbeat.send_heartbeat", side_effect=RuntimeError("connection refused")
    ):
        assert maybe_send_heartbeat(db) is False
    assert "connection refused" in cfg.last_error
    # Left unset so the monitor still sees a gap and alerts.
    assert cfg.last_ping_at is None
