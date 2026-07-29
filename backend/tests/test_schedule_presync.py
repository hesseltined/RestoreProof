"""
Purpose: Unit tests for schedule-window host inventory pre-sync.
Author: Doug Hesseltine
Created: 2026-07-28
Modified: 2026-07-28
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.restore import sync_enabled_hosts_for_schedule


def _host(
    host_id: int,
    *,
    name: str = "pve",
    enabled: bool = True,
    last_sync_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=host_id,
        name=name,
        enabled=enabled,
        last_sync_at=last_sync_at,
        last_error=None,
    )


def test_sync_skips_hosts_already_synced_this_window() -> None:
    window = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)
    host = _host(1, last_sync_at=window + timedelta(minutes=1))
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.all.return_value = [host]

    with patch("app.services.restore.sync_host_guests") as sync_fn:
        assert sync_enabled_hosts_for_schedule(db, window) == 0
        sync_fn.assert_not_called()


def test_sync_refreshes_stale_enabled_hosts() -> None:
    window = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)
    stale = _host(1, last_sync_at=window - timedelta(hours=1))
    fresh = _host(2, name="pve2", last_sync_at=window)
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.all.return_value = [stale, fresh]

    with patch("app.services.restore.sync_host_guests", return_value=12) as sync_fn:
        assert sync_enabled_hosts_for_schedule(db, window) == 1
        sync_fn.assert_called_once_with(db, stale)


def test_sync_records_error_but_continues() -> None:
    window = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)
    bad = _host(1, name="bad")
    good = _host(2, name="good")
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.all.return_value = [bad, good]

    def _side_effect(_db, host):
        if host.id == 1:
            raise RuntimeError("api down")
        return 3

    with patch("app.services.restore.sync_host_guests", side_effect=_side_effect):
        assert sync_enabled_hosts_for_schedule(db, window) == 1
    assert "Schedule pre-sync failed" in (bad.last_error or "")
    db.commit.assert_called()
