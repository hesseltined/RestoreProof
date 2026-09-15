"""
Purpose: Unit tests for pre-restore validation (guest exists, job, snapshot).
Author: Doug Hesseltine
Created: 2026-07-31
Modified: 2026-07-31
Version: 1.0.0
"""

import asyncio
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.proxmox import ProxmoxClient
from app.services.restore import notify_run, preflight_restore_check


class FakeClient:
    """Minimal stand-in for ProxmoxClient covering the pre-flight calls."""

    def __init__(self, resources: list[dict], jobs: list[dict], backups: list[dict]):
        self._resources = resources
        self._jobs = jobs
        self._backups = backups

    def cluster_resources(self, resource_type: str | None = None) -> list[dict]:
        return self._resources

    def list_backup_jobs(self) -> list[dict]:
        return self._jobs

    def find_pbs_backups(self, node: str, vmid: int) -> list[dict]:
        return self._backups


def _guest(vmid: int = 133) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        vmid=vmid,
        name="immich",
        node="pve2",
        status="running",
        host_id=1,
        in_backup_job=False,
        backup_job_enabled=False,
        backup_job_summary="",
        backup_snapshot_count=0,
        last_backup_at=None,
    )


def _host() -> SimpleNamespace:
    return SimpleNamespace(id=1, name="pve")


RESOURCES = [
    {"vmid": 133, "type": "lxc", "node": "pve2", "name": "immich", "status": "running"},
    {"vmid": 100, "type": "qemu", "node": "pve1", "name": "dc01", "status": "running"},
]
JOB = {"id": "backup-weekly", "type": "vzdump", "enabled": 1, "schedule": "sun 01:00", "vmid": "133"}
SNAPSHOT = {"volid": "pbs:backup/ct/133/2026-07-30T00:27:56Z", "ctime": 1785457676}


def test_guest_missing_from_proxmox_is_flagged() -> None:
    guest = _guest(vmid=999)
    result = preflight_restore_check(
        MagicMock(), guest, _host(), client=FakeClient(RESOURCES, [JOB], [SNAPSHOT])
    )
    assert result.ok is False
    assert result.guest_missing is True
    assert result.skip is True
    assert "no longer exists" in result.reason


def test_guest_not_in_any_backup_job_is_blocked() -> None:
    guest = _guest()
    result = preflight_restore_check(
        MagicMock(), guest, _host(), client=FakeClient(RESOURCES, [], [SNAPSHOT])
    )
    assert result.ok is False
    assert result.guest_missing is False
    # No backup configured means no restore was expected: skip, never fail.
    assert result.skip is True
    assert "not in any Proxmox backup job" in result.reason
    assert guest.in_backup_job is False


def test_scheduled_guest_without_snapshot_is_blocked() -> None:
    guest = _guest()
    result = preflight_restore_check(
        MagicMock(), guest, _host(), client=FakeClient(RESOURCES, [JOB], [])
    )
    assert result.ok is False
    assert result.skip is True
    assert "No PBS backup exists yet" in result.reason
    assert guest.in_backup_job is True
    assert guest.backup_snapshot_count == 0


def test_scheduled_guest_with_snapshot_passes() -> None:
    guest = _guest()
    result = preflight_restore_check(
        MagicMock(), guest, _host(), client=FakeClient(RESOURCES, [JOB], [SNAPSHOT])
    )
    assert result.ok is True
    assert guest.in_backup_job is True
    assert guest.backup_job_enabled is True
    assert guest.backup_snapshot_count == 1
    assert guest.last_backup_at is not None
    assert guest.last_backup_at.tzinfo is timezone.utc


def test_unreachable_host_is_not_reported_as_missing_guest() -> None:
    class Broken(FakeClient):
        def cluster_resources(self, resource_type: str | None = None) -> list[dict]:
            raise ConnectionError("connection refused")

    result = preflight_restore_check(
        MagicMock(), _guest(), _host(), client=Broken([], [], [])
    )
    assert result.ok is False
    assert result.unreachable is True
    assert result.guest_missing is False
    # A connectivity problem is a real error, not a "nothing to do" skip.
    assert result.skip is False


def test_skipped_run_sends_no_notification() -> None:
    run = SimpleNamespace(status="skipped", error_message="not in any backup job")
    with patch("app.services.restore.send_email") as send:
        asyncio.run(notify_run(MagicMock(), run))
    send.assert_not_called()


def test_backup_index_groups_snapshots_by_vmid() -> None:
    client = ProxmoxClient.__new__(ProxmoxClient)
    items = [
        {"vmid": 133, "volid": "pbs:backup/ct/133/a", "ctime": 100, "_stype": "pbs"},
        {"vmid": 133, "volid": "pbs:backup/ct/133/b", "ctime": 200, "_stype": "pbs"},
        {"vmid": 100, "volid": "pbs:backup/vm/100/a", "ctime": 150, "_stype": "pbs"},
    ]
    client._backup_items = lambda node: items  # type: ignore[method-assign]

    index = client.pbs_backup_index("pve2")
    assert set(index) == {133, 100}
    assert len(index[133]) == 2
    # Newest first so callers can read last_backup_at from position 0.
    assert index[133][0]["ctime"] == 200
    assert index.get(112, []) == []
