"""
Purpose: Tests for the dashboard recent-runs limit selector.
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.1.0
"""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.api.settings import dashboard
from app.schemas import DashboardOut


class FakeQuery:
    """Chainable stand-in that records the LIMIT applied, if any."""

    def __init__(self, limits: list[int]):
        self._limits = limits

    def order_by(self, *a, **k) -> "FakeQuery":
        return self

    def filter(self, *a, **k) -> "FakeQuery":
        return self

    def limit(self, n: int) -> "FakeQuery":
        self._limits.append(n)
        return self

    def all(self) -> list:
        return []

    def first(self):
        return None

    def count(self) -> int:
        return 0


class FakeDB:
    def __init__(self):
        self.limits: list[int] = []

    def query(self, *a, **k) -> FakeQuery:
        return FakeQuery(self.limits)


def _call(recent_limit: int) -> tuple[DashboardOut, FakeDB]:
    db = FakeDB()
    settings = SimpleNamespace(
        setup_completed=True, schedule_enabled=False, global_cron="0 2 * * *"
    )
    lock = SimpleNamespace(held_by=None, run_id=None)
    with patch("app.api.settings.get_app_settings", return_value=settings), patch(
        "app.api.settings.locks.get_lock", return_value=lock
    ), patch("app.api.settings.remediation_for_runs", return_value={}):
        out = dashboard(recent_limit=recent_limit, db=db, _=None)
    return out, db


@pytest.mark.parametrize("choice", [10, 20, 30, 40, 50])
def test_each_numeric_choice_limits_the_query(choice: int) -> None:
    _, db = _call(choice)
    assert db.limits == [choice]


def test_zero_means_all_and_applies_no_limit() -> None:
    """The "All" option must not silently cap the list."""
    _, db = _call(0)
    assert db.limits == []


def test_default_limit_matches_the_previous_fixed_page_size() -> None:
    """Clients that send no preference keep the original 10-row dashboard."""
    assert inspect.signature(dashboard).parameters["recent_limit"].default.default == 10


def test_total_is_reported_alongside_the_page() -> None:
    out, _ = _call(10)
    assert out.recent_runs_total == 0
    assert out.recent_runs == []


def test_total_defaults_to_zero_for_older_clients() -> None:
    """recent_runs_total is additive; omitting it must not break validation."""
    assert _dashboard_out().recent_runs_total == 0


def test_total_is_carried_through_when_supplied() -> None:
    assert _dashboard_out(recent_runs_total=143).recent_runs_total == 143


def test_non_numeric_total_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _dashboard_out(recent_runs_total="many")


def _dashboard_out(**kw) -> DashboardOut:
    base = {
        "setup_completed": True,
        "schedule_enabled": False,
        "global_cron": "0 2 * * *",
        "lock_held": False,
        "lock_held_by": None,
        "lock_run_id": None,
        "recent_runs": [],
        "guest_count": 0,
        "excluded_count": 0,
        "host_count": 0,
        "next_due": None,
    }
    base.update(kw)
    return DashboardOut(**base)
