"""
Purpose: Unit tests for ntfy push URL parsing and run payload building.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.0.0
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.pusher import (
    MAX_MESSAGE_CHARS,
    PRIORITIES,
    PushConfigError,
    build_run_push,
    send_push,
    split_topic_url,
)


def test_splits_hosted_topic_url() -> None:
    assert split_topic_url("https://ntfy.sh/restoreproof") == (
        "https://ntfy.sh",
        "restoreproof",
    )


def test_splits_self_hosted_url_with_path_prefix() -> None:
    base, topic = split_topic_url("https://home.example.com/ntfy/restoreproof")
    assert base == "https://home.example.com/ntfy"
    assert topic == "restoreproof"


def test_tolerates_whitespace_and_trailing_slash() -> None:
    assert split_topic_url("  https://ntfy.sh/alerts/  ") == ("https://ntfy.sh", "alerts")


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "ntfy.sh/topic", "https://ntfy.sh", "https://ntfy.sh/", "ftp://ntfy.sh/topic"],
)
def test_rejects_unusable_urls(bad: str) -> None:
    with pytest.raises(PushConfigError):
        split_topic_url(bad)


def _run(status: str, **kw) -> SimpleNamespace:
    base = {
        "status": status,
        "source_name": "immich",
        "source_vmid": 133,
        "used_fallback_backup": False,
        "result_summary": "Restored, booted, verified.",
        "error_message": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


CTX = {"guest_name": "immich", "vmid": 133, "run_url": "https://rp.lab/runs/42"}


def test_failure_push_is_high_priority_and_carries_the_error() -> None:
    run = _run("failed", error_message="No PBS backups found", result_summary="")
    payload = build_run_push(run, CTX)
    assert "FAILED" in payload["title"]
    assert "VMID 133" in payload["title"]
    assert payload["message"] == "No PBS backups found"
    assert PRIORITIES[payload["priority"]] > PRIORITIES["default"]
    assert payload["click_url"] == "https://rp.lab/runs/42"


def test_success_push_also_alerts() -> None:
    """
    Successes are sent at high priority too. Below "high", ntfy uses a low-importance
    Android channel that shows no pop-up and makes no sound, which looks like a
    dropped notification.
    """
    payload = build_run_push(_run("success"), CTX)
    assert "passed" in payload["title"]
    assert PRIORITIES[payload["priority"]] > PRIORITIES["default"]
    assert payload["tags"] == ["white_check_mark"]


def test_fallback_backup_success_is_called_out() -> None:
    payload = build_run_push(_run("success", used_fallback_backup=True), CTX)
    assert "older backup" in payload["title"]
    assert payload["tags"] == ["warning"]
    assert PRIORITIES[payload["priority"]] > PRIORITIES["default"]


@pytest.mark.parametrize("status", ["success", "failed"])
def test_no_run_notification_is_sent_silently(status: str) -> None:
    """Guard the rule directly: nothing goes out below heads-up priority."""
    payload = build_run_push(_run(status), CTX)
    assert PRIORITIES[payload["priority"]] >= PRIORITIES["high"]


def test_failure_without_details_still_has_a_message() -> None:
    payload = build_run_push(_run("failed", error_message="", result_summary=""), CTX)
    assert payload["message"].strip()


def test_send_push_posts_json_with_numeric_priority() -> None:
    """ntfy's JSON API needs an int priority; the rest of the app uses names."""
    sent: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeClient:
        def __init__(self, **kwargs):
            sent["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            sent["url"] = url
            sent["json"] = json
            sent["headers"] = headers
            return FakeResponse()

    db = MagicMock()
    settings = SimpleNamespace(
        url="https://ntfy.sh/restoreproof-abc",
        token_enc="",
        verify_ssl=True,
    )
    with patch("app.services.pusher.get_push_settings", return_value=settings), patch(
        "app.services.pusher.httpx.AsyncClient", FakeClient
    ):
        asyncio.run(
            send_push(
                db,
                title="t",
                message="x" * (MAX_MESSAGE_CHARS + 200),
                priority="high",
                tags=["rotating_light"],
                click_url="https://rp.lab/runs/42",
            )
        )

    assert sent["url"] == "https://ntfy.sh/"
    assert sent["json"]["topic"] == "restoreproof-abc"
    assert sent["json"]["priority"] == PRIORITIES["high"]
    assert sent["json"]["tags"] == ["rotating_light"]
    assert sent["json"]["click"] == "https://rp.lab/runs/42"
    # Long bodies are trimmed so the notification stays readable on a phone.
    assert len(sent["json"]["message"]) <= MAX_MESSAGE_CHARS
    assert "Authorization" not in sent["headers"]


def test_send_push_sends_bearer_token_when_set() -> None:
    sent: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            sent["headers"] = headers
            return FakeResponse()

    settings = SimpleNamespace(url="https://ntfy.sh/t", token_enc="enc", verify_ssl=True)
    with patch("app.services.pusher.get_push_settings", return_value=settings), patch(
        "app.services.pusher.decrypt_secret", return_value="tk_secret"
    ), patch("app.services.pusher.httpx.AsyncClient", FakeClient):
        asyncio.run(send_push(MagicMock(), title="t", message="m"))

    assert sent["headers"]["Authorization"] == "Bearer tk_secret"


def test_send_push_raises_with_server_detail() -> None:
    class FakeResponse:
        status_code = 403
        text = "forbidden: topic is reserved"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            return FakeResponse()

    settings = SimpleNamespace(url="https://ntfy.sh/t", token_enc="", verify_ssl=True)
    with patch("app.services.pusher.get_push_settings", return_value=settings), patch(
        "app.services.pusher.httpx.AsyncClient", FakeClient
    ):
        with pytest.raises(RuntimeError, match="403"):
            asyncio.run(send_push(MagicMock(), title="t", message="m"))
