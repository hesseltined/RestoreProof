"""
Purpose: Cluster SSH routing and single-inventory fingerprint checks.
Author: Doug Hesseltine
Created: 2026-09-27
Modified: 2026-09-27
Version: 1.0.0
"""

from app.services.proxmox import cluster_fingerprint
from app.services.restore import duplicate_cluster_owner
from app.services.ssh_keys import SSHSession, command_on_proxmox_node, nodes_match


def test_local_node_runs_command_in_place() -> None:
    raw = "printf 'screendump /tmp/restoreproof-9001.ppm\\n' | qm monitor 9001"
    assert command_on_proxmox_node("pve11-2", "pve11-2", raw) == raw
    assert command_on_proxmox_node("PVE11-2", "pve11-2", raw) == raw
    assert command_on_proxmox_node("pve11-2.lan", "pve11-2", raw) == raw
    assert command_on_proxmox_node("pve11-1", "", raw) == raw


def test_other_node_hops_over_cluster_root_ssh() -> None:
    raw = "printf 'screendump /tmp/restoreproof-9001.ppm\\n' | qm monitor 9001"
    cmd = command_on_proxmox_node("pve11-1", "pve11-2", raw)
    assert cmd.startswith("ssh ")
    assert "BatchMode=yes" in cmd
    assert "root@pve11-2" in cmd
    assert "qm monitor 9001" in cmd
    assert "pve11-1" not in cmd


def test_nodes_match_ignores_case_and_domain() -> None:
    assert nodes_match("pve11-1", "pve11-1")
    assert nodes_match("pve11-1.example.com", "PVE11-1")
    assert not nodes_match("pve11-1", "pve11-2")
    assert not nodes_match("", "pve11-2")


class _Std:
    def __init__(self, text: str) -> None:
        self._text = text.encode()
        self.channel = self

    def read(self) -> bytes:
        return self._text

    def recv_exit_status(self) -> int:
        return 0


def test_bound_session_hops_screendump_off_the_landing_node() -> None:
    session = SSHSession("10.250.0.11", 22, "root", "/tmp/restoreproof-key")
    calls: list[str] = []

    def exec_command(command: str, timeout: int = 120) -> tuple[None, _Std, _Std]:
        calls.append(command)
        if command == "hostname -s":
            return None, _Std("pve11-1\n"), _Std("")
        return None, _Std("ok\n"), _Std("")

    session.client = type("Client", (), {"exec_command": staticmethod(exec_command)})()
    session.bind_node("pve11-2")
    code, out, err = session.run("qm monitor 9001")
    assert code == 0
    assert out.strip() == "ok"
    assert err == ""
    assert calls[0] == "hostname -s"
    assert "root@pve11-2" in calls[1]
    assert "qm monitor 9001" in calls[1]


def test_bound_session_stays_local_on_the_owning_node() -> None:
    session = SSHSession("10.250.0.12", 22, "root", "/tmp/restoreproof-key")
    calls: list[str] = []

    def exec_command(command: str, timeout: int = 120) -> tuple[None, _Std, _Std]:
        calls.append(command)
        if command == "hostname -s":
            return None, _Std("pve11-2\n"), _Std("")
        return None, _Std("ok\n"), _Std("")

    session.client = type("Client", (), {"exec_command": staticmethod(exec_command)})()
    session.bind_node("pve11-2")
    session.run("qm monitor 9001")
    assert calls == ["hostname -s", "qm monitor 9001"]


def test_cluster_fingerprint_is_stable_across_api_nodes() -> None:
    rows = [
        {"type": "cluster", "name": "pve-lab", "nodes": 2},
        {"type": "node", "name": "pve11-2", "ip": "10.250.0.12", "online": 1},
        {"type": "node", "name": "pve11-1", "ip": "10.250.0.11", "online": 1},
    ]
    again = [
        {"type": "node", "name": "pve11-1", "ip": "10.250.0.11"},
        {"type": "cluster", "name": "pve-lab"},
        {"type": "node", "name": "pve11-2", "ip": "10.250.0.12"},
    ]
    expected = "pve-lab|pve11-1@10.250.0.11,pve11-2@10.250.0.12"
    assert cluster_fingerprint(rows) == expected
    assert cluster_fingerprint(again) == expected
    assert cluster_fingerprint([]) == ""


def test_duplicate_cluster_owner_is_lowest_enabled_host() -> None:
    assert duplicate_cluster_owner(1, True, [(2, True), (3, True)]) is None
    assert duplicate_cluster_owner(2, True, [(1, True)]) == 1
    assert duplicate_cluster_owner(4, True, [(2, False), (3, True)]) == 3
    assert duplicate_cluster_owner(3, True, [(2, False), (4, True)]) is None
    assert duplicate_cluster_owner(2, False, [(1, True)]) == 1
    assert duplicate_cluster_owner(1, False, []) is None
