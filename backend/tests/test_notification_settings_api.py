"""
Purpose: Tests that push/heartbeat settings save while still incomplete.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.0.0
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.settings import update_heartbeat, update_push
from app.schemas import HeartbeatUpdate, PushUpdate


def _push_row(**kw) -> SimpleNamespace:
    base = {
        "enabled": False,
        "provider": "ntfy",
        "url": "",
        "token_enc": "",
        "verify_ssl": True,
        "on_success": False,
        "on_failure": True,
        "push_ok_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _beat_row(**kw) -> SimpleNamespace:
    base = {
        "enabled": False,
        "url": "",
        "interval_seconds": 300,
        "verify_ssl": True,
        "last_ping_at": None,
        "last_error": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_push_enables_before_a_topic_url_exists() -> None:
    """
    Turning the toggle on first must save. Blocking it stranded users who had not
    generated a topic yet, and the send path already skips a URL-less config.
    """
    row = _push_row()
    with patch("app.api.settings.get_push_settings", return_value=row):
        out = update_push(PushUpdate(enabled=True), db=MagicMock(), _=None)
    assert row.enabled is True
    assert out.enabled is True
    assert out.url == ""


def test_heartbeat_saves_interval_before_a_url_exists() -> None:
    row = _beat_row()
    with patch("app.api.settings.get_heartbeat_settings", return_value=row):
        out = update_heartbeat(
            HeartbeatUpdate(enabled=True, interval_seconds=600), db=MagicMock(), _=None
        )
    assert row.enabled is True
    assert row.interval_seconds == 600
    assert out.interval_seconds == 600


def test_push_rejects_a_malformed_topic_url() -> None:
    with patch("app.api.settings.get_push_settings", return_value=_push_row()):
        with pytest.raises(HTTPException) as exc:
            update_push(PushUpdate(url="ntfy.sh/no-scheme"), db=MagicMock(), _=None)
    assert exc.value.status_code == 400


def test_heartbeat_rejects_a_malformed_ping_url() -> None:
    with patch("app.api.settings.get_heartbeat_settings", return_value=_beat_row()):
        with pytest.raises(HTTPException) as exc:
            update_heartbeat(HeartbeatUpdate(url="/api/push/abc"), db=MagicMock(), _=None)
    assert exc.value.status_code == 400


def test_push_toggles_off_are_persisted() -> None:
    """`False` must not be skipped the way an omitted field is."""
    row = _push_row(enabled=True, on_failure=True, url="https://ntfy.sh/t")
    with patch("app.api.settings.get_push_settings", return_value=row):
        update_push(PushUpdate(enabled=False, on_failure=False), db=MagicMock(), _=None)
    assert row.enabled is False
    assert row.on_failure is False


def test_push_blank_token_keeps_the_stored_secret() -> None:
    row = _push_row(token_enc="already-encrypted")
    with patch("app.api.settings.get_push_settings", return_value=row):
        update_push(PushUpdate(token=""), db=MagicMock(), _=None)
    assert row.token_enc == "already-encrypted"


def test_push_dash_token_clears_the_stored_secret() -> None:
    row = _push_row(token_enc="already-encrypted")
    with patch("app.api.settings.get_push_settings", return_value=row):
        out = update_push(PushUpdate(token="-"), db=MagicMock(), _=None)
    assert row.token_enc == ""
    assert out.token_set is False
