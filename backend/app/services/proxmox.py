"""
Purpose: Proxmox VE REST API client (token auth).
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.3.0
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


class ProxmoxAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ProxmoxClient:
    def __init__(
        self,
        api_url: str,
        token_id: str,
        token_secret: str,
        verify_ssl: bool = False,
        timeout: float = 120.0,
    ):
        base = api_url.rstrip("/")
        if not base.endswith("/api2/json"):
            if base.endswith("/api2"):
                base = base + "/json"
            else:
                base = base + "/api2/json"
        self.base_url = base
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.headers = {
            "Authorization": f"PVEAPIToken={token_id}={token_secret}",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=self.headers,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        with self._client() as client:
            resp = client.request(method, path, **kwargs)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            if resp.status_code >= 400:
                raise ProxmoxAPIError(
                    f"Proxmox API {method} {path} failed: {resp.status_code} {data}",
                    status_code=resp.status_code,
                    body=data,
                )
            return data.get("data")

    def version(self) -> Any:
        return self.request("GET", "/version")

    def nodes(self) -> list[dict]:
        return self.request("GET", "/nodes") or []

    def qemu_list(self, node: str) -> list[dict]:
        return self.request("GET", f"/nodes/{node}/qemu") or []

    def lxc_list(self, node: str) -> list[dict]:
        return self.request("GET", f"/nodes/{node}/lxc") or []

    def storage_list(self) -> list[dict]:
        return self.request("GET", "/storage") or []

    def node_storage(self, node: str) -> list[dict]:
        return self.request("GET", f"/nodes/{node}/storage") or []

    def storage_content(self, node: str, storage: str, content: Optional[str] = None) -> list[dict]:
        params = {}
        if content:
            params["content"] = content
        return self.request("GET", f"/nodes/{node}/storage/{storage}/content", params=params) or []

    def find_pbs_backups(self, node: str, vmid: int) -> list[dict]:
        """Return backup volumes for a VMID across PBS-capable storages, newest first."""
        backups: list[dict] = []
        for st in self.node_storage(node):
            storage_id = st.get("storage")
            content = str(st.get("content") or "")
            stype = str(st.get("type") or "")
            if "backup" not in content and stype != "pbs":
                continue
            try:
                items = self.storage_content(node, storage_id, content="backup")
            except ProxmoxAPIError:
                continue
            for item in items:
                if int(item.get("vmid") or -1) != int(vmid):
                    continue
                # Prefer PBS / vzdump backup entries
                volid = item.get("volid") or ""
                if stype == "pbs" or "backup/" in volid or volid.startswith(f"{storage_id}:backup/"):
                    item = dict(item)
                    item["_storage"] = storage_id
                    item["_stype"] = stype
                    backups.append(item)
        backups.sort(key=lambda b: b.get("ctime") or 0, reverse=True)
        # v1: PBS only — keep pbs type or volids that look like PBS
        pbs_only = [b for b in backups if b.get("_stype") == "pbs" or "backup/vm/" in str(b.get("volid")) or "backup/ct/" in str(b.get("volid"))]
        return pbs_only or backups

    def wait_task(
        self,
        node: str,
        upid: str,
        timeout: int = 3600,
        poll: float = 2.0,
        on_poll: Optional[Any] = None,
        on_poll_every: float = 2.0,
    ) -> dict:
        deadline = time.time() + timeout
        last_cb = 0.0
        while time.time() < deadline:
            status = self.request("GET", f"/nodes/{node}/tasks/{quote(upid, safe='')}/status")
            if status and status.get("status") == "stopped":
                if status.get("exitstatus") != "OK":
                    raise ProxmoxAPIError(f"Task failed: {status.get('exitstatus')}", body=status)
                if on_poll:
                    try:
                        on_poll(status or {})
                    except Exception:  # noqa: BLE001
                        pass
                return status
            now = time.time()
            if on_poll and now - last_cb >= on_poll_every:
                try:
                    on_poll(status or {})
                except Exception:  # noqa: BLE001
                    pass
                last_cb = now
            time.sleep(poll)
        raise ProxmoxAPIError(f"Task timed out: {upid}")

    def task_log(self, node: str, upid: str, start: int = 0, limit: int = 50) -> list[dict]:
        """Return recent task log lines (newest last)."""
        data = self.request(
            "GET",
            f"/nodes/{node}/tasks/{quote(upid, safe='')}/log",
            params={"start": start, "limit": limit},
        )
        if isinstance(data, list):
            return data
        return []

    def task_progress_pct(self, node: str, upid: str, status: Optional[dict] = None) -> Optional[float]:
        """Best-effort percent (0–100) from task status and/or log."""
        status = status or self.request(
            "GET", f"/nodes/{node}/tasks/{quote(upid, safe='')}/status"
        )
        if not status:
            return None
        raw = status.get("progress")
        if raw is not None:
            try:
                val = float(raw)
                if 0.0 <= val <= 1.0:
                    return round(val * 100.0, 1)
                if 0.0 <= val <= 100.0:
                    return round(val, 1)
            except (TypeError, ValueError):
                pass
            if isinstance(raw, str) and raw.strip().endswith("%"):
                try:
                    return round(float(raw.strip().rstrip("%")), 1)
                except ValueError:
                    pass
        # Fall back to scanning recent log lines for "NN%" patterns
        try:
            lines = self.task_log(node, upid, start=0, limit=40)
        except Exception:  # noqa: BLE001
            return None
        pct: Optional[float] = None
        for entry in lines:
            text = str(entry.get("t") or entry.get("text") or "")
            for m in _PCT_RE.findall(text):
                try:
                    v = float(m)
                    if 0.0 <= v <= 100.0:
                        pct = v
                except ValueError:
                    continue
        return round(pct, 1) if pct is not None else None

    def restore_qemu(
        self,
        node: str,
        vmid: int,
        archive: str,
        storage: Optional[str] = None,
        unique: bool = True,
        start: bool = False,
        force: bool = False,
    ) -> str:
        data: dict[str, Any] = {
            "vmid": vmid,
            "archive": archive,
            "unique": 1 if unique else 0,
            "start": 1 if start else 0,
            "force": 1 if force else 0,
        }
        if storage:
            data["storage"] = storage
        return self.request("POST", f"/nodes/{node}/qemu", data=data)

    def restore_lxc(
        self,
        node: str,
        vmid: int,
        archive: str,
        storage: Optional[str] = None,
        unique: bool = True,
        start: bool = False,
        force: bool = False,
        ostemplate: bool = False,
    ) -> str:
        # LXC restore uses POST /nodes/{node}/lxc with ostemplate/archive
        data: dict[str, Any] = {
            "vmid": vmid,
            "ostemplate": archive,
            "unique": 1 if unique else 0,
            "start": 1 if start else 0,
            "force": 1 if force else 0,
            "restore": 1,
        }
        if storage:
            data["storage"] = storage
        return self.request("POST", f"/nodes/{node}/lxc", data=data)

    def qemu_config(self, node: str, vmid: int) -> dict:
        return self.request("GET", f"/nodes/{node}/qemu/{vmid}/config") or {}

    def lxc_config(self, node: str, vmid: int) -> dict:
        return self.request("GET", f"/nodes/{node}/lxc/{vmid}/config") or {}

    def qemu_set_config(self, node: str, vmid: int, **kwargs: Any) -> Any:
        return self.request("PUT", f"/nodes/{node}/qemu/{vmid}/config", data=kwargs)

    def lxc_set_config(self, node: str, vmid: int, **kwargs: Any) -> Any:
        return self.request("PUT", f"/nodes/{node}/lxc/{vmid}/config", data=kwargs)

    def qemu_unlink_nets(self, node: str, vmid: int) -> list[str]:
        cfg = self.qemu_config(node, vmid)
        keys = [k for k in cfg.keys() if str(k).startswith("net")]
        if not keys:
            return []
        # Proxmox accepts comma-separated delete=net0,net1
        self.qemu_set_config(node, vmid, delete=",".join(sorted(keys)))
        return keys

    def lxc_unlink_nets(self, node: str, vmid: int) -> list[str]:
        cfg = self.lxc_config(node, vmid)
        keys = [k for k in cfg.keys() if str(k).startswith("net")]
        if not keys:
            return []
        self.lxc_set_config(node, vmid, delete=",".join(sorted(keys)))
        return keys

    def qemu_unlink_hostdevs(self, node: str, vmid: int) -> list[str]:
        """Remove USB/PCI host passthrough devices from a test VM config."""
        cfg = self.qemu_config(node, vmid)
        keys = qemu_hostdev_keys(cfg)
        if not keys:
            return []
        self.qemu_set_config(node, vmid, delete=",".join(sorted(keys)))
        return keys

    def qemu_status(self, node: str, vmid: int) -> dict:
        return self.request("GET", f"/nodes/{node}/qemu/{vmid}/status/current") or {}

    def lxc_status(self, node: str, vmid: int) -> dict:
        return self.request("GET", f"/nodes/{node}/lxc/{vmid}/status/current") or {}

    def qemu_start(self, node: str, vmid: int) -> str:
        return self.request("POST", f"/nodes/{node}/qemu/{vmid}/status/start")

    def lxc_start(self, node: str, vmid: int) -> str:
        return self.request("POST", f"/nodes/{node}/lxc/{vmid}/status/start")

    def qemu_stop(self, node: str, vmid: int) -> str:
        return self.request("POST", f"/nodes/{node}/qemu/{vmid}/status/stop")

    def lxc_stop(self, node: str, vmid: int) -> str:
        return self.request("POST", f"/nodes/{node}/lxc/{vmid}/status/stop")

    def qemu_delete(self, node: str, vmid: int, purge: bool = True) -> str:
        params = {"purge": 1, "destroy-unreferenced-disks": 1} if purge else {}
        return self.request("DELETE", f"/nodes/{node}/qemu/{vmid}", params=params)

    def lxc_delete(self, node: str, vmid: int, purge: bool = True) -> str:
        params = {"purge": 1, "destroy-unreferenced-disks": 1} if purge else {}
        return self.request("DELETE", f"/nodes/{node}/lxc/{vmid}", params=params)

    def next_id(self) -> int:
        return int(self.request("GET", "/cluster/nextid"))

    def cluster_resources(self, resource_type: Optional[str] = None) -> list[dict]:
        params = {}
        if resource_type:
            params["type"] = resource_type
        return self.request("GET", "/cluster/resources", params=params) or []


def qemu_hostdev_keys(cfg: dict) -> list[str]:
    """Config keys for host USB/PCI passthrough (usb0, hostpci0, …)."""
    return [
        str(k)
        for k in cfg.keys()
        if str(k).startswith("usb") or str(k).startswith("hostpci")
    ]


def is_hostdev_privilege_error(exc: BaseException) -> bool:
    """True when Proxmox rejected USB/PCI config because the caller is not root."""
    msg = str(exc).lower()
    if "only root can set" not in msg:
        return False
    return "usb" in msg or "hostpci" in msg
