"""
Purpose: Unit tests for GitHub / Docker Hub version comparison.
Author: Doug Hesseltine
Created: 2026-09-17
Modified: 2026-09-17
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.updates import (
    cache_is_fresh,
    fetch_dockerhub_latest,
    fetch_github_latest,
    get_update_status,
    is_newer,
    normalize_version,
    version_tuple,
)
from app.version import APP_VERSION


def test_normalize_strips_v_prefix() -> None:
    assert normalize_version("v1.6.5") == "1.6.5"
    assert normalize_version("1.6.5") == "1.6.5"


def test_newer_handles_two_digit_patch() -> None:
    assert is_newer("1.6.10", "1.6.5") is True
    assert is_newer("1.6.4", "1.6.5") is False
    assert is_newer("1.6.5", "1.6.5") is False
    assert is_newer("2.0.0", "1.9.9") is True


def test_version_tuple_ignores_latest() -> None:
    assert version_tuple("latest") == (0,)
    assert version_tuple("v1.6.4") == (1, 6, 4)


def test_github_latest_release_wins() -> None:
    def fake_get(url: str):
        if url.endswith("/releases/latest"):
            return {
                "tag_name": "v1.7.0",
                "html_url": "https://github.com/hesseltined/RestoreProof/releases/tag/v1.7.0",
                "body": "Color-coded digests.",
                "draft": False,
                "prerelease": False,
            }
        return []

    with patch("app.services.updates._get_json", side_effect=fake_get):
        probe = fetch_github_latest("hesseltined/RestoreProof")
    assert probe is not None
    assert probe.version == "1.7.0"
    assert probe.source == "github"
    assert "Color-coded" in probe.notes


def test_dockerhub_skips_latest_tag() -> None:
    payload = {
        "results": [
            {"name": "latest"},
            {"name": "1.6.4"},
            {"name": "1.6.3"},
        ]
    }
    with patch("app.services.updates._get_json", return_value=payload):
        probe = fetch_dockerhub_latest("yesitsmedoug/restoreproof-api")
    assert probe is not None
    assert probe.version == "1.6.4"
    assert probe.source == "dockerhub"


def test_status_hides_banner_when_dismissed() -> None:
    settings = SimpleNamespace(
        update_check_enabled=True,
        update_latest_version="9.9.9",
        update_latest_url="https://github.com/hesseltined/RestoreProof/releases",
        update_latest_notes="",
        update_latest_source="github",
        update_last_checked_at=datetime.now(timezone.utc),
        update_dismissed_version="9.9.9",
    )
    payload = get_update_status(MagicMock(), settings, refresh=False)
    assert payload["update_available"] is True
    assert payload["dismissed"] is True
    assert payload["current_version"] == APP_VERSION
    assert is_newer("9.9.9", APP_VERSION) is True


def test_disabled_check_never_reports_available() -> None:
    settings = SimpleNamespace(
        update_check_enabled=False,
        update_latest_version="9.9.9",
        update_latest_url="",
        update_latest_notes="",
        update_latest_source="github",
        update_last_checked_at=None,
        update_dismissed_version="",
    )
    payload = get_update_status(MagicMock(), settings, refresh=False)
    assert payload["update_available"] is False
    assert payload["check_enabled"] is False


def test_cache_freshness() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    fresh = SimpleNamespace(update_last_checked_at=now - timedelta(hours=1))
    stale = SimpleNamespace(update_last_checked_at=now - timedelta(hours=7))
    empty = SimpleNamespace(update_last_checked_at=None)
    assert cache_is_fresh(fresh, now=now) is True
    assert cache_is_fresh(stale, now=now) is False
    assert cache_is_fresh(empty, now=now) is False
