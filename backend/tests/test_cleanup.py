"""
Purpose: Unit tests for test-guest cleanup (protection flag + pool sweep).
Author: Doug Hesseltine
Created: 2026-09-11
Modified: 2026-09-11
Version: 1.0.0
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.proxmox import (
    ProxmoxAPIError,
    guest_is_protected,
    leftover_test_pool_guests,
)
from app.services.restore import cleanup_test_guest, sweep_leftover_test_guests


def test_guest_is_protected_truthy_values() -> None:
    assert guest_is_protected({"protection": 1}) is True
    assert guest_is_protected({"protection": "1"}) is True
    assert guest_is_protected({"protection": True}) is True
    assert guest_is_protected({"protection": 0}) is False
    assert guest_is_protected({}) is False
    assert guest_is_protected({"protection": "off"}) is False


def test_leftover_pool_skips_busy_production_and_nodeless() -> None:
    resources = [
        {"vmid": 139, "node": "pve2", "type": "lxc", "name": "steerage"},
        {"vmid": 9000, "node": "pve2", "type": "lxc", "name": "npm"},
        {"vmid": 9001, "node": "pve2", "type": "lxc", "name": "npm2"},
        {"vmid": 9010, "node": "pve1", "type": "qemu", "name": "win"},
        {"vmid": 9002, "node": "", "type": "lxc"},
        {"vmid": 100, "node": "pve1", "type": "qemu", "name": "dc01"},
    ]
    found = leftover_test_pool_guests(resources, 9000, 9099, busy_vmids={9001})
    assert found == [(9000, "pve2", "lxc"), (9010, "pve1", "qemu")]


class _FakeLxcClient:
    def __init__(self, *, protected: bool = True, missing: bool = False) -> None:
        self.cfg = {"protection": 1 if protected else 0, "hostname": "npm"}
        self.missing = missing
        self.status = "stopped"
        self.protection_cleared = False
        self.delete_force: bool | None = None
        self.delete_called = False

    def clear_guest_protection(self, node: str, vmid: int, guest_type: str) -> bool:
        if self.missing:
            raise ProxmoxAPIError("does not exist", status_code=404)
        if guest_is_protected(self.cfg):
            self.cfg["protection"] = 0
            self.protection_cleared = True
            return True
        return False

    def lxc_status(self, node: str, vmid: int) -> dict:
        if self.missing:
            raise ProxmoxAPIError("does not exist", status_code=404)
        return {"status": self.status}

    def lxc_delete(self, node: str, vmid: int, purge: bool = True, force: bool = False) -> str:
        if guest_is_protected(self.cfg):
            raise ProxmoxAPIError("CT is protected", status_code=500)
        self.delete_called = True
        self.delete_force = force
        return "UPID:delete"

    def wait_task(self, node: str, upid: str, timeout: int = 600) -> dict:
        return {"status": "stopped", "exitstatus": "OK"}


def test_cleanup_clears_protection_then_force_deletes_lxc() -> None:
    client = _FakeLxcClient(protected=True)
    assert cleanup_test_guest(client, "lxc", "pve2", 9000) == "deleted"
    assert client.protection_cleared is True
    assert client.delete_called is True
    assert client.delete_force is True


def test_cleanup_already_gone() -> None:
    client = _FakeLxcClient(missing=True)
    assert cleanup_test_guest(client, "lxc", "pve2", 9000) == "already gone"


def _host() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="pve",
        ssh_host="",
        ssh_port=22,
        ssh_user="root",
        ssh_private_key_path="",
        test_vmid_start=9000,
        test_vmid_end=9099,
        enabled=True,
    )


@patch("app.services.restore.cleanup_test_guest")
@patch("app.services.restore._client_for_host")
@patch("app.services.restore.busy_test_vmids", return_value=set())
def test_sweep_destroys_leftover_pool_guests(
    _busy: MagicMock, client_fn: MagicMock, cleanup_fn: MagicMock
) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        _host()
    ]
    client = MagicMock()
    client.cluster_resources.return_value = [
        {"vmid": 139, "node": "pve2", "type": "lxc"},
        {"vmid": 9000, "node": "pve2", "type": "lxc"},
        {"vmid": 9001, "node": "pve2", "type": "lxc"},
    ]
    client_fn.return_value = client
    cleanup_fn.return_value = "deleted"

    assert sweep_leftover_test_guests(db) == 2
    assert cleanup_fn.call_count == 2
    cleanup_fn.assert_any_call(client, "lxc", "pve2", 9000, ssh=None)
    cleanup_fn.assert_any_call(client, "lxc", "pve2", 9001, ssh=None)


@patch("app.services.restore.cleanup_test_guest")
@patch("app.services.restore._client_for_host")
@patch("app.services.restore.busy_test_vmids", return_value={9000})
def test_sweep_skips_vmid_in_use_by_running_restore(
    _busy: MagicMock, client_fn: MagicMock, cleanup_fn: MagicMock
) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        _host()
    ]
    client = MagicMock()
    client.cluster_resources.return_value = [
        {"vmid": 9000, "node": "pve2", "type": "lxc"},
    ]
    client_fn.return_value = client

    assert sweep_leftover_test_guests(db) == 0
    cleanup_fn.assert_not_called()
