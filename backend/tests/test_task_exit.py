"""
Purpose: Unit tests for Proxmox task exitstatus success rules.
Author: Doug Hesseltine
Created: 2026-07-23
Modified: 2026-07-23
Version: 1.0.0
"""

from app.services.proxmox import is_successful_task_exit


def test_ok_is_success() -> None:
    assert is_successful_task_exit("OK") is True


def test_warnings_count_is_success() -> None:
    # Windows/OVMF qmstart advisory (ms-cert=2023k) — must not fail restore drills
    assert is_successful_task_exit("WARNINGS: 1") is True
    assert is_successful_task_exit("WARNINGS: 2") is True
    assert is_successful_task_exit("warnings: 1") is True


def test_real_failures_are_not_success() -> None:
    assert is_successful_task_exit(None) is False
    assert is_successful_task_exit("") is False
    assert is_successful_task_exit("ERROR") is False
    assert is_successful_task_exit("interrupted") is False
    assert is_successful_task_exit("command failed") is False
