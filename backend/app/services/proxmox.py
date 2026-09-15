"""
Purpose: Proxmox VE REST API client (token auth).
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-11
Version: 1.8.0
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


def parse_backup_job_vmids(job: dict) -> tuple[bool, set[int], set[int]]:
    """
    Parse a Proxmox cluster backup job into (covers_all, include_vmids, exclude_vmids).

    ``covers_all`` is True when the job backs up every guest (minus excludes).
    """
    exclude: set[int] = set()
    raw_excl = job.get("exclude")
    if raw_excl is not None and str(raw_excl).strip() != "":
        for part in str(raw_excl).split(","):
            part = part.strip()
            if part.isdigit():
                exclude.add(int(part))

    all_flag = job.get("all")
    covers_all = all_flag in (1, True, "1", "true", "True")

    include: set[int] = set()
    raw_vmid = job.get("vmid")
    if raw_vmid is not None and str(raw_vmid).strip() != "":
        for part in str(raw_vmid).split(","):
            part = part.strip()
            if part.isdigit():
                include.add(int(part))

    if covers_all:
        return True, set(), exclude
    return False, include, exclude


def vmid_in_backup_jobs(
    vmid: int,
    jobs: list[dict],
    *,
    known_vmids: Optional[set[int]] = None,
    require_enabled: bool = False,
) -> tuple[bool, list[dict]]:
    """
    Return (is_covered, matching_jobs) for a guest VMID against vzdump jobs.

    When ``require_enabled`` is True, only jobs with enabled=1 are considered.
    ``known_vmids`` is used when a job has ``all: 1`` (every guest on the host).
    """
    matching: list[dict] = []
    for job in jobs:
        if str(job.get("type") or "vzdump") not in ("vzdump", ""):
            continue
        enabled = job.get("enabled", 1)
        is_enabled = enabled not in (0, False, "0", "false", "False")
        if require_enabled and not is_enabled:
            continue
        covers_all, include, exclude = parse_backup_job_vmids(job)
        if int(vmid) in exclude:
            continue
        if covers_all:
            if known_vmids is None or int(vmid) in known_vmids:
                matching.append(job)
            continue
        if int(vmid) in include:
            matching.append(job)
    return bool(matching), matching


def is_successful_task_exit(exitstatus: object) -> bool:
    """
    True when a Proxmox task completed successfully.

    Proxmox uses exitstatus \"OK\" for clean success, and strings like
    \"WARNINGS: 1\" when the task finished with non-fatal warnings
    (common on qmstart for Windows/OVMF guests missing ms-cert=2023k).
    Those warnings must not be treated as restore-test failures.
    """
    if exitstatus is None:
        return False
    es = str(exitstatus).strip()
    if es == "OK":
        return True
    return es.upper().startswith("WARNING")


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

    def _backup_items(self, node: str) -> list[dict]:
        """Raw backup volumes from every PBS-capable storage on a node."""
        items: list[dict] = []
        for st in self.node_storage(node):
            storage_id = st.get("storage")
            content = str(st.get("content") or "")
            stype = str(st.get("type") or "")
            if "backup" not in content and stype != "pbs":
                continue
            try:
                found = self.storage_content(node, storage_id, content="backup")
            except ProxmoxAPIError:
                continue
            for item in found:
                volid = item.get("volid") or ""
                if stype == "pbs" or "backup/" in volid or volid.startswith(f"{storage_id}:backup/"):
                    entry = dict(item)
                    entry["_storage"] = storage_id
                    entry["_stype"] = stype
                    items.append(entry)
        return items

    @staticmethod
    def _prefer_pbs(backups: list[dict]) -> list[dict]:
        """Newest-first, preferring true PBS volumes over other backup targets."""
        backups.sort(key=lambda b: b.get("ctime") or 0, reverse=True)
        pbs_only = [
            b
            for b in backups
            if b.get("_stype") == "pbs"
            or "backup/vm/" in str(b.get("volid"))
            or "backup/ct/" in str(b.get("volid"))
        ]
        return pbs_only or backups

    def find_pbs_backups(self, node: str, vmid: int) -> list[dict]:
        """Return backup volumes for a VMID across PBS-capable storages, newest first."""
        backups = [
            item
            for item in self._backup_items(node)
            if int(item.get("vmid") or -1) == int(vmid)
        ]
        return self._prefer_pbs(backups)

    def pbs_backup_index(self, node: str) -> dict[int, list[dict]]:
        """
        Map every VMID on a node to its backup volumes (newest first).

        One pass over node storages so inventory sync does not issue a separate
        content listing per guest.
        """
        grouped: dict[int, list[dict]] = {}
        for item in self._backup_items(node):
            try:
                vmid = int(item.get("vmid"))
            except (TypeError, ValueError):
                continue
            grouped.setdefault(vmid, []).append(item)
        return {vmid: self._prefer_pbs(items) for vmid, items in grouped.items()}

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
                exitstatus = status.get("exitstatus")
                if not is_successful_task_exit(exitstatus):
                    raise ProxmoxAPIError(f"Task failed: {exitstatus}", body=status)
                if str(exitstatus or "").upper().startswith("WARNING"):
                    logger.warning(
                        "Proxmox task %s finished with warnings: %s", upid, exitstatus
                    )
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

    def qemu_delete(
        self, node: str, vmid: int, purge: bool = True, skiplock: bool = False
    ) -> str:
        params: dict[str, Any] = {}
        if purge:
            params["purge"] = 1
            params["destroy-unreferenced-disks"] = 1
        if skiplock:
            params["skiplock"] = 1
        return self.request("DELETE", f"/nodes/{node}/qemu/{vmid}", params=params)

    def lxc_delete(
        self, node: str, vmid: int, purge: bool = True, force: bool = False
    ) -> str:
        params: dict[str, Any] = {}
        if purge:
            params["purge"] = 1
            params["destroy-unreferenced-disks"] = 1
        if force:
            params["force"] = 1
        return self.request("DELETE", f"/nodes/{node}/lxc/{vmid}", params=params)

    def clear_guest_protection(self, node: str, vmid: int, guest_type: str) -> bool:
        """Clear the Proxmox protection flag. Returns True if it was set."""
        if guest_type == "qemu":
            cfg = self.qemu_config(node, vmid)
            setter = self.qemu_set_config
        else:
            cfg = self.lxc_config(node, vmid)
            setter = self.lxc_set_config
        if not guest_is_protected(cfg):
            return False
        setter(node, vmid, protection=0)
        return True

    def next_id(self) -> int:
        return int(self.request("GET", "/cluster/nextid"))

    def list_backup_jobs(self) -> list[dict]:
        """Return Proxmox vzdump / cluster backup jobs (from /cluster/backup)."""
        data = self.request("GET", "/cluster/backup") or []
        if isinstance(data, list):
            return data
        return []

    def cluster_resources(self, resource_type: Optional[str] = None) -> list[dict]:
        params = {}
        if resource_type:
            params["type"] = resource_type
        return self.request("GET", "/cluster/resources", params=params) or []


def guest_is_protected(cfg: dict) -> bool:
    """True when a QEMU/LXC config has Proxmox's protection flag set."""
    raw = cfg.get("protection")
    if raw in (1, True, "1", "true", "True", "yes", "on"):
        return True
    try:
        return int(raw) == 1
    except (TypeError, ValueError):
        return False


def leftover_test_pool_guests(
    resources: list[dict],
    pool_start: int,
    pool_end: int,
    busy_vmids: Optional[set[int]] = None,
) -> list[tuple[int, str, str]]:
    """
    Return (vmid, node, guest_type) for cluster resources in a host's test pool.

    Skips VMIDs currently used by a queued/running restore (``busy_vmids``).
    """
    busy = busy_vmids or set()
    found: list[tuple[int, str, str]] = []
    for res in resources:
        try:
            vmid = int(res.get("vmid"))
        except (TypeError, ValueError):
            continue
        if vmid < int(pool_start) or vmid > int(pool_end):
            continue
        if vmid in busy:
            continue
        node = str(res.get("node") or "").strip()
        if not node:
            continue
        rtype = str(res.get("type") or "")
        guest_type = "lxc" if rtype == "lxc" else "qemu"
        found.append((vmid, node, guest_type))
    found.sort(key=lambda item: item[0])
    return found


def qemu_hostdev_keys(cfg: dict) -> list[str]:
    """Config keys for host USB/PCI passthrough (usb0, hostpci0, …)."""
    return [
        str(k)
        for k in cfg.keys()
        if str(k).startswith("usb") or str(k).startswith("hostpci")
    ]


_MP_KEY_RE = re.compile(r"^mp\d+$")


def lxc_host_mount_keys(cfg: dict) -> list[str]:
    """
    LXC mpN keys that are host bind/device mounts (not storage volumes).

    Bind/device mounts use an absolute host path as the volume (e.g.
    ``/mnt/share,mp=/data``). Storage volumes use ``storage:vol`` syntax.
    Only root@pam (not API tokens) may restore these via the API.
    """
    keys: list[str] = []
    for k, v in cfg.items():
        ks = str(k)
        if not _MP_KEY_RE.match(ks):
            continue
        volume = str(v or "").split(",", 1)[0].strip()
        if volume.startswith("/"):
            keys.append(ks)
    return keys


def is_hostdev_privilege_error(exc: BaseException) -> bool:
    """True when Proxmox rejected USB/PCI config because the caller is not root."""
    msg = str(exc).lower()
    if "only root can set" not in msg:
        return False
    return "usb" in msg or "hostpci" in msg


def is_lxc_mount_privilege_error(exc: BaseException) -> bool:
    """True when CT restore/config needs root for bind or device mounts."""
    msg = str(exc).lower()
    if "only possible for root" in msg and (
        "bind mount" in msg or "device mount" in msg
    ):
        return True
    if "only root" in msg and ("bind mount" in msg or "device mount" in msg):
        return True
    return False
