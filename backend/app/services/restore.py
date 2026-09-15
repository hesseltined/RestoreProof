"""
Purpose: Full restore → boot → evidence → cleanup cycle for one guest.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-11
Version: 1.15.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Template
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Guest, ProxmoxHost, RestoreRun
from app.security import decrypt_secret
from app.services import locks
from app.services.bootstrap import get_app_settings, get_push_settings
from app.services.email_templates import build_notification_context, screenshot_attachment
from app.services.mailer import parse_addr_list, send_email
from app.services.pusher import build_run_push, send_push
from app.services.proxmox import (
    ProxmoxAPIError,
    ProxmoxClient,
    is_hostdev_privilege_error,
    is_lxc_mount_privilege_error,
    is_successful_task_exit,
    leftover_test_pool_guests,
    lxc_host_mount_keys,
    qemu_hostdev_keys,
    vmid_in_backup_jobs,
)
from app.services.ssh_keys import SSHSession, convert_screendump_to_png

logger = logging.getLogger(__name__)


def _log(run: RestoreRun, line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    run.log_text = (run.log_text or "") + f"[{stamp}] {line}\n"


def _set_progress(
    db: Session,
    run: RestoreRun,
    *,
    pct: object = ...,
    label: Optional[str] = None,
    upid: Optional[str] = None,
    node: Optional[str] = None,
) -> None:
    if pct is not ...:
        if pct is None:
            run.progress_pct = None
        else:
            run.progress_pct = max(0.0, min(100.0, float(pct)))  # type: ignore[arg-type]
    if label is not None:
        run.progress_label = label
    if upid is not None:
        run.proxmox_upid = upid
    if node is not None:
        run.proxmox_node = node


def _client_for_host(host: ProxmoxHost) -> ProxmoxClient:
    secret = decrypt_secret(host.token_secret_enc)
    return ProxmoxClient(
        api_url=host.api_url,
        token_id=host.token_id,
        token_secret=secret,
        verify_ssl=host.verify_ssl,
    )


def pick_test_vmid(client: ProxmoxClient, host: ProxmoxHost) -> int:
    used = set()
    for res in client.cluster_resources(resource_type="vm"):
        if res.get("vmid") is not None:
            used.add(int(res["vmid"]))
    for vid in range(host.test_vmid_start, host.test_vmid_end + 1):
        if vid not in used:
            return vid
    raise RuntimeError(
        f"No free test VMID in pool {host.test_vmid_start}-{host.test_vmid_end}"
    )


def pick_restore_storage(
    client: ProxmoxClient,
    host: ProxmoxHost,
    node: str,
    preferred: str,
    guest_type: str = "qemu",
) -> Optional[str]:
    storages = client.node_storage(node)
    by_id = {s.get("storage"): s for s in storages}
    need = "images" if guest_type == "qemu" else "rootdir"

    def usable(sid: str) -> bool:
        st = by_id.get(sid)
        if not st:
            return False
        content = str(st.get("content") or "")
        return need in content

    if preferred and usable(preferred):
        return preferred
    if host.preferred_restore_storage and usable(host.preferred_restore_storage):
        return host.preferred_restore_storage
    for st in storages:
        sid = st.get("storage")
        if sid and usable(sid):
            return sid
    return None


def storage_hint_from_guest_config(cfg: dict, guest_type: str) -> Optional[str]:
    """Best-effort storage id from the source guest's first disk (e.g. VMs:vm-101-disk-1)."""
    if guest_type == "qemu":
        prefixes = ("scsi", "ide", "sata", "virtio", "efidisk", "tpm")
    else:
        prefixes = ("rootfs", "mp")
    for key, raw in cfg.items():
        ks = str(key)
        if not any(ks == p or ks.startswith(p) for p in prefixes):
            continue
        val = str(raw or "")
        if ":" not in val:
            continue
        sid = val.split(":", 1)[0].strip()
        if sid:
            return sid
    return None


def is_pbs_data_error(exc: BaseException) -> bool:
    """True when PBS cannot read/verify backup data (missing chunk, corrupt snapshot, etc.)."""
    msg = str(exc).lower()
    if ".chunks/" in msg:
        return True
    if "no such file or directory" in msg and ("chunk" in msg or "pbs-restore" in msg or "backup" in msg):
        return True
    if "not completely restored" in msg:
        return True
    if "download and verify" in msg and "failed" in msg:
        return True
    if "reading file" in msg and "failed" in msg:
        return True
    return False


def should_try_older_backup(exc: BaseException) -> bool:
    """Whether a failed restore of one snapshot should fall through to an older backup."""
    if is_hostdev_privilege_error(exc):
        return False
    if is_lxc_mount_privilege_error(exc):
        return False
    msg = str(exc).lower()
    if "ssh is required" in msg:
        return False
    if "global restore lock" in msg:
        return False
    if "no free test vmid" in msg:
        return False
    if "no restore storage" in msg:
        return False
    # Snapshot-specific restore failures (PBS data, qmrestore/pct, Proxmox task) → try older
    return True


def _backup_ctime_label(backup: dict) -> str:
    ctime = backup.get("ctime")
    if ctime is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ctime), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return ""


def format_backup_inventory(backups: list[dict], *, limit: int = 12) -> str:
    """Human-readable list of available PBS backups (newest first)."""
    lines: list[str] = []
    for i, b in enumerate(backups[:limit], start=1):
        volid = str(b.get("volid") or "")
        when = _backup_ctime_label(b)
        size = b.get("size")
        size_s = ""
        if isinstance(size, (int, float)) and size > 0:
            gib = float(size) / (1024**3)
            size_s = f", ~{gib:.1f} GiB" if gib >= 1 else f", ~{float(size) / (1024**2):.0f} MiB"
        tag = " [LATEST]" if i == 1 else ""
        when_s = f" ({when}{size_s})" if when or size_s else ""
        lines.append(f"  {i}. {volid}{when_s}{tag}")
    if len(backups) > limit:
        lines.append(f"  … and {len(backups) - limit} more")
    return "\n".join(lines)


def build_env_diagnostics(
    *,
    host: ProxmoxHost,
    guest: Guest,
    node: str,
    guest_type: str,
    test_vmid: Optional[int],
    storage: Optional[str],
    backups: list[dict],
    latest_volid: str,
    used_volid: str,
    used_index: Optional[int],
    attempted: int,
    used_fallback: bool,
    restore_method: str,
    source_hostdevs: list[str],
    source_bind_mounts: list[str],
    ssh_ready: bool,
    failed_newer: list[tuple[str, str]],
    manual_cmd: str = "",
    success: bool,
) -> str:
    """Clear summary for UI/email: backup inventory + environment context."""
    total = len(backups)
    lines: list[str] = []

    if success and used_fallback:
        lines.append(
            "⚠ NOT THE LATEST BACKUP — RestoreProof used an older snapshot because "
            "one or more newer backups failed to restore."
        )
        lines.append(
            f"Used backup #{used_index} of {total} available (1 = newest)."
        )
        lines.append(f"Used:    {used_volid}")
        lines.append(f"Latest:  {latest_volid}  ← failed; see log for details")
        if failed_newer:
            lines.append("Newer backups that failed:")
            for vol, err in failed_newer:
                short = err.replace("\n", " ")
                if len(short) > 180:
                    short = short[:177] + "…"
                lines.append(f"  - {vol}")
                lines.append(f"    {short}")
        lines.append(
            "Action: verify/repair the latest PBS snapshot, or take a fresh backup of this guest."
        )
    elif success:
        lines.append(f"Restored from the latest backup (1 of {total} available).")
        lines.append(f"Backup: {used_volid}")
    else:
        lines.append(f"Restore FAILED after trying {attempted} of {total} available backup(s).")
        lines.append(f"Last tried: {used_volid or '(none)'}")
        if latest_volid:
            lines.append(f"Latest available: {latest_volid}")
        if failed_newer or attempted:
            lines.append("Snapshots attempted (newest → older):")
            for vol, err in failed_newer:
                short = err.replace("\n", " ")
                if len(short) > 180:
                    short = short[:177] + "…"
                lines.append(f"  - {vol}")
                lines.append(f"    {short}")
            if used_volid and (not failed_newer or failed_newer[-1][0] != used_volid):
                lines.append(f"  - {used_volid} (final attempt)")

    lines.append("")
    lines.append(f"PBS backups available for VMID {guest.vmid}: {total}")
    if backups:
        lines.append(format_backup_inventory(backups))
    lines.append("")
    lines.append("Environment:")
    lines.append(f"  Host: {host.name} ({host.api_url})")
    lines.append(f"  Node: {node}")
    lines.append(f"  Guest: {guest.name} (VMID {guest.vmid}, {guest_type})")
    lines.append(f"  Test VMID: {test_vmid if test_vmid is not None else '—'}")
    lines.append(f"  Restore storage: {storage or '—'}")
    lines.append(f"  Restore method: {restore_method}")
    lines.append(f"  SSH configured: {'yes' if ssh_ready else 'no'}")
    if source_hostdevs:
        lines.append(f"  Source host passthrough: {', '.join(source_hostdevs)}")
    if source_bind_mounts:
        lines.append(f"  Source CT bind/device mounts: {', '.join(source_bind_mounts)}")
    if manual_cmd:
        lines.append("")
        lines.append(f"Manual retry on node {node} as root:")
        lines.append(f"  {manual_cmd}")
    if not success:
        lines.append("")
        lines.append("Suggested next steps:")
        lines.append("  1. Confirm the same qmrestore/pct command fails in the Proxmox UI/CLI.")
        lines.append("  2. On PBS, verify the datastore / check for missing chunks after GC.")
        lines.append("  3. Take a fresh backup of this guest, then re-run the restore test.")
        lines.append("  4. Until fixed, exclude this guest from the schedule to avoid repeat alerts.")
    return "\n".join(lines)


def _normalize_guest_type(guest_type: str) -> str:
    return "qemu" if guest_type == "qemu" else "lxc"


def _retryable_cleanup_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "lock" in msg or "timeout" in msg or "protect" in msg


def cleanup_test_guest(
    client: ProxmoxClient,
    guest_type: str,
    node: str,
    test_vmid: int,
    ssh: Optional[SSHSession] = None,
) -> str:
    """Stop and destroy a leftover test qemu/lxc guest. Returns a short status message."""
    guest_type = _normalize_guest_type(guest_type)
    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            try:
                if client.clear_guest_protection(node, test_vmid, guest_type):
                    logger.info("Cleared protection on test %s %s", guest_type, test_vmid)
            except ProxmoxAPIError as exc:
                if exc.status_code == 404:
                    return "already gone"
                if ssh is not None:
                    try:
                        ssh.clear_protection(guest_type, test_vmid)
                    except Exception:  # noqa: BLE001
                        pass
                elif not _retryable_cleanup_error(exc):
                    raise

            if guest_type == "qemu":
                try:
                    st = client.qemu_status(node, test_vmid)
                    if st.get("status") == "running":
                        upid = client.qemu_stop(node, test_vmid)
                        client.wait_task(node, upid, timeout=300)
                except ProxmoxAPIError as exc:
                    if exc.status_code == 404:
                        return "already gone"
                    raise
                upid = client.qemu_delete(node, test_vmid, purge=True)
                client.wait_task(node, upid, timeout=600)
                return "deleted"

            try:
                st = client.lxc_status(node, test_vmid)
                if st.get("status") == "running":
                    upid = client.lxc_stop(node, test_vmid)
                    client.wait_task(node, upid, timeout=300)
            except ProxmoxAPIError as exc:
                if exc.status_code == 404:
                    return "already gone"
                raise
            upid = client.lxc_delete(node, test_vmid, purge=True, force=True)
            client.wait_task(node, upid, timeout=600)
            return "deleted"
        except ProxmoxAPIError as exc:
            last_err = exc
            if exc.status_code == 404:
                return "already gone"
            if ssh is not None and _retryable_cleanup_error(exc):
                try:
                    ssh.unlock_guest(guest_type, test_vmid)
                    ssh.clear_protection(guest_type, test_vmid)
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2 * attempt)
                continue
            if _retryable_cleanup_error(exc):
                time.sleep(3 * attempt)
                continue
            if ssh is not None:
                try:
                    return ssh.destroy_guest(guest_type, test_vmid)
                except Exception as ssh_exc:  # noqa: BLE001
                    last_err = ssh_exc
                    raise last_err
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if ssh is not None:
                try:
                    return ssh.destroy_guest(guest_type, test_vmid)
                except Exception as ssh_exc:  # noqa: BLE001
                    last_err = ssh_exc
                    raise last_err
            raise
    if ssh is not None:
        try:
            return ssh.destroy_guest(guest_type, test_vmid)
        except Exception as ssh_exc:  # noqa: BLE001
            last_err = ssh_exc
    if last_err:
        raise last_err
    return "failed"


def busy_test_vmids(db: Session) -> set[int]:
    """Test VMIDs currently allocated to a queued or running restore."""
    busy: set[int] = set()
    rows = (
        db.query(RestoreRun.test_vmid)
        .filter(
            RestoreRun.status.in_(("queued", "running")),
            RestoreRun.test_vmid.isnot(None),
        )
        .all()
    )
    for (vmid,) in rows:
        try:
            busy.add(int(vmid))
        except (TypeError, ValueError):
            continue
    return busy


def sweep_leftover_test_guests(db: Session) -> int:
    """
    Destroy leftover guests sitting in each host's test VMID pool.

    Source backups often copy ``protection: 1``, which blocks the per-run
    delete. This sweep unprotects and destroys anything still in the pool
    that is not owned by a queued/running restore.
    """
    busy = busy_test_vmids(db)
    destroyed = 0
    hosts = (
        db.query(ProxmoxHost)
        .filter(ProxmoxHost.enabled.is_(True))
        .order_by(ProxmoxHost.id.asc())
        .all()
    )
    for host in hosts:
        ssh = None
        try:
            client = _client_for_host(host)
            if host.ssh_host and host.ssh_private_key_path:
                try:
                    ssh = SSHSession(
                        host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
                    )
                    ssh.__enter__()
                except Exception:  # noqa: BLE001
                    ssh = None
            leftovers = leftover_test_pool_guests(
                client.cluster_resources(resource_type="vm"),
                host.test_vmid_start,
                host.test_vmid_end,
                busy,
            )
            for vmid, node, guest_type in leftovers:
                try:
                    msg = cleanup_test_guest(client, guest_type, node, vmid, ssh=ssh)
                    logger.info(
                        "Swept leftover test %s %s on %s: %s",
                        guest_type,
                        vmid,
                        host.name,
                        msg,
                    )
                    if msg != "already gone":
                        destroyed += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to sweep test VMID %s (%s) on %s",
                        vmid,
                        guest_type,
                        host.name,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Test-pool sweep failed for host %s", host.name)
        finally:
            if ssh is not None:
                try:
                    ssh.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
    return destroyed


def recover_orphaned_runs(db: Session) -> int:
    """
    After a worker crash/restart, mark stuck 'running' runs failed, attempt test-VM cleanup,
    and force-release the global lock.
    """
    orphaned = db.query(RestoreRun).filter(RestoreRun.status == "running").all()
    recovered = 0
    for run in orphaned:
        _log(
            run,
            "Recovered after worker restart — restore was interrupted before finish/cleanup",
        )
        host = db.query(ProxmoxHost).filter_by(id=run.host_id).first() if run.host_id else None
        guest = db.query(Guest).filter_by(id=run.guest_id).first() if run.guest_id else None
        node = (guest.node if guest else "") or ""
        guest_type = run.guest_type or (guest.guest_type if guest else "qemu")
        if host and run.test_vmid and node:
            try:
                client = _client_for_host(host)
                ssh = None
                if host.ssh_host and host.ssh_private_key_path:
                    try:
                        ssh = SSHSession(
                            host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
                        )
                        ssh.__enter__()
                    except Exception:  # noqa: BLE001
                        ssh = None
                try:
                    msg = cleanup_test_guest(
                        client, guest_type, node, int(run.test_vmid), ssh=ssh
                    )
                    _log(run, f"Orphan cleanup of test VMID {run.test_vmid}: {msg}")
                finally:
                    if ssh is not None:
                        try:
                            ssh.__exit__(None, None, None)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001
                _log(run, f"Orphan cleanup failed for VMID {run.test_vmid}: {exc}")
                logger.exception("orphan cleanup failed for run %s", run.id)
        else:
            _log(run, "No test VMID/node recorded — clean up leftover guests in the test pool manually if needed")
        run.status = "failed"
        run.error_message = (
            "Interrupted: worker restarted while this restore was in progress. "
            "Re-run the test. Any leftover test guest was cleaned up if possible."
        )
        run.finished_at = datetime.now(timezone.utc)
        recovered += 1

    prev = locks.force_release(db)
    if prev is not None or orphaned:
        logger.info("Recovered %s orphaned run(s); released lock (prior run_id=%s)", recovered, prev)
    db.commit()
    return recovered


def _backup_job_summary(jobs: list[dict]) -> str:
    """Short UI string: job id and schedule for covering vzdump jobs."""
    parts: list[str] = []
    for job in jobs[:4]:
        jid = str(job.get("id") or "job")
        sched = str(job.get("schedule") or "").strip()
        enabled = job.get("enabled", 1) not in (0, False, "0", "false", "False")
        label = f"{jid} ({sched})" if sched else jid
        if not enabled:
            label += " [disabled]"
        parts.append(label)
    if len(jobs) > 4:
        parts.append(f"+{len(jobs) - 4} more")
    return ", ".join(parts)


def _skip_queued_runs_for_guest(db: Session, guest: Guest, reason: str) -> int:
    """Skip not-yet-started runs so a vanished guest is never restored."""
    pending = (
        db.query(RestoreRun)
        .filter(RestoreRun.guest_id == guest.id, RestoreRun.status == "queued")
        .all()
    )
    for run in pending:
        run.status = "skipped"
        run.error_message = reason
        run.progress_label = "Skipped"
        run.progress_pct = 100.0
        run.finished_at = datetime.now(timezone.utc)
        _log(run, f"Run skipped: {reason}")
    return len(pending)


def sync_host_guests(db: Session, host: ProxmoxHost) -> int:
    client = _client_for_host(host)
    client.version()
    resources = client.cluster_resources(resource_type="vm")
    try:
        backup_jobs = client.list_backup_jobs()
    except ProxmoxAPIError as exc:
        logger.warning("Could not list backup jobs for host %s: %s", host.name, exc)
        backup_jobs = []

    backup_index: dict[str, dict[int, list[dict]]] = {}

    def backups_for(node: str, vmid: int) -> list[dict]:
        """Cached per-node PBS snapshot listing."""
        if node not in backup_index:
            try:
                backup_index[node] = client.pbs_backup_index(node)
            except ProxmoxAPIError as exc:
                logger.warning("Could not list backups on node %s: %s", node, exc)
                backup_index[node] = {}
        return backup_index[node].get(int(vmid), [])

    seen: set[int] = set()
    count = 0
    for res in resources:
        vmid = res.get("vmid")
        if vmid is None:
            continue
        if host.test_vmid_start <= int(vmid) <= host.test_vmid_end:
            continue
        rtype = res.get("type")
        if rtype not in ("qemu", "lxc"):
            continue
        seen.add(int(vmid))
        guest = (
            db.query(Guest)
            .filter(Guest.host_id == host.id, Guest.vmid == int(vmid))
            .first()
        )
        if not guest:
            guest = Guest(host_id=host.id, vmid=int(vmid), guest_type=rtype)
            db.add(guest)
        guest.name = res.get("name") or guest.name or f"{rtype}-{vmid}"
        guest.guest_type = rtype
        guest.node = res.get("node") or guest.node
        guest.status = res.get("status") or ""
        maxcpu = res.get("maxcpu")
        try:
            guest.cpu_cores = int(maxcpu) if maxcpu is not None else None
        except (TypeError, ValueError):
            guest.cpu_cores = None
        maxmem = res.get("maxmem")
        try:
            guest.memory_bytes = int(maxmem) if maxmem is not None else None
        except (TypeError, ValueError):
            guest.memory_bytes = None
        maxdisk = res.get("maxdisk")
        try:
            guest.disk_bytes = int(maxdisk) if maxdisk is not None else None
        except (TypeError, ValueError):
            guest.disk_bytes = None
        count += 1

    # Apply backup-job membership and PBS snapshot inventory once the full VMID
    # set is known (needed for jobs that back up "all" guests).
    for g in db.query(Guest).filter(Guest.host_id == host.id).all():
        if g.vmid not in seen:
            continue
        covered, matching = vmid_in_backup_jobs(
            g.vmid, backup_jobs, known_vmids=seen, require_enabled=False
        )
        g.in_backup_job = covered
        g.backup_job_enabled = any(
            j.get("enabled", 1) not in (0, False, "0", "false", "False") for j in matching
        )
        g.backup_job_summary = _backup_job_summary(matching) if matching else ""

        snapshots = backups_for(g.node, g.vmid)
        g.backup_snapshot_count = len(snapshots)
        newest_ctime = snapshots[0].get("ctime") if snapshots else None
        g.last_backup_at = (
            datetime.fromtimestamp(int(newest_ctime), tz=timezone.utc)
            if newest_ctime
            else None
        )

    existing = db.query(Guest).filter(Guest.host_id == host.id).all()
    removed = 0
    for g in existing:
        if g.vmid not in seen:
            _skip_queued_runs_for_guest(
                db,
                g,
                f"VMID {g.vmid} ({g.name}) no longer exists on host {host.name}",
            )
            db.delete(g)
            removed += 1
    if removed:
        logger.info("Sync removed %s guest(s) no longer on host %s", removed, host.name)

    host.last_sync_at = datetime.now(timezone.utc)
    host.last_error = None
    db.commit()
    return count


class PreflightResult:
    """
    Outcome of the pre-restore validation for one guest.

    ``skip`` marks the "nothing was ever expected to be restored" cases — the
    guest is gone, or no backup is configured/exists. Those are not errors: the
    run is recorded as skipped and no failure notification is sent. Only genuine
    problems (an unreachable host) are treated as failures.
    """

    def __init__(
        self,
        ok: bool,
        reason: str = "",
        *,
        guest_missing: bool = False,
        unreachable: bool = False,
        skip: bool = False,
    ):
        self.ok = ok
        self.reason = reason
        self.guest_missing = guest_missing
        self.unreachable = unreachable
        self.skip = skip


def preflight_restore_check(
    db: Session,
    guest: Guest,
    host: ProxmoxHost,
    client: Optional[ProxmoxClient] = None,
) -> PreflightResult:
    """
    Verify a guest can actually be restore-tested, against live Proxmox state.

    Checks, in order: the guest still exists on the host, it belongs to a
    Datacenter backup job, and at least one PBS snapshot exists. Findings are
    written back to the Guest row so the UI reflects them without a full sync.
    """
    try:
        client = client or _client_for_host(host)
        resources = client.cluster_resources(resource_type="vm")
    except Exception as exc:  # noqa: BLE001
        return PreflightResult(
            False,
            f"Could not reach Proxmox host {host.name}: {exc}",
            unreachable=True,
        )

    match = None
    known_vmids: set[int] = set()
    for res in resources:
        vmid = res.get("vmid")
        if vmid is None:
            continue
        known_vmids.add(int(vmid))
        if int(vmid) == int(guest.vmid) and res.get("type") in ("qemu", "lxc"):
            match = res

    if match is None:
        return PreflightResult(
            False,
            f"VMID {guest.vmid} ({guest.name}) no longer exists on host {host.name}. "
            "Sync the host to drop it from the inventory.",
            guest_missing=True,
            skip=True,
        )

    # Keep node/name current: a migrated guest would otherwise restore on the wrong node.
    guest.node = match.get("node") or guest.node
    guest.name = match.get("name") or guest.name
    guest.status = match.get("status") or guest.status

    try:
        jobs = client.list_backup_jobs()
    except ProxmoxAPIError as exc:
        logger.warning("Could not list backup jobs for host %s: %s", host.name, exc)
        jobs = []
    covered, matching = vmid_in_backup_jobs(
        guest.vmid, jobs, known_vmids=known_vmids, require_enabled=False
    )
    guest.in_backup_job = covered
    guest.backup_job_enabled = any(
        j.get("enabled", 1) not in (0, False, "0", "false", "False") for j in matching
    )
    guest.backup_job_summary = _backup_job_summary(matching) if matching else ""
    if not covered:
        db.commit()
        return PreflightResult(
            False,
            f"VMID {guest.vmid} ({guest.name}) is not in any Proxmox backup job "
            "(Datacenter → Backup), so there is nothing to restore-test.",
            skip=True,
        )

    try:
        backups = client.find_pbs_backups(guest.node, guest.vmid)
    except ProxmoxAPIError as exc:
        return PreflightResult(
            False,
            f"Could not list backups for VMID {guest.vmid}: {exc}",
            unreachable=True,
        )
    guest.backup_snapshot_count = len(backups)
    newest_ctime = backups[0].get("ctime") if backups else None
    guest.last_backup_at = (
        datetime.fromtimestamp(int(newest_ctime), tz=timezone.utc) if newest_ctime else None
    )
    db.commit()

    if not backups:
        job_hint = guest.backup_job_summary or "its backup job"
        return PreflightResult(
            False,
            f"No PBS backup exists yet for VMID {guest.vmid} ({guest.name}). "
            f"It is scheduled by {job_hint} but has not produced a snapshot — "
            "run that backup job first.",
            skip=True,
        )

    return PreflightResult(True)


def sync_enabled_hosts_for_schedule(db: Session, window_start: datetime) -> int:
    """Refresh Proxmox inventory once per schedule window before guest selection.

    Deletes DB guests that no longer exist on the host so the scheduler cannot
    pick removed VMs/CTs. Hosts already synced at or after ``window_start`` are
    skipped. Returns the number of hosts successfully synced this call.
    """
    hosts = (
        db.query(ProxmoxHost)
        .filter(ProxmoxHost.enabled.is_(True))
        .order_by(ProxmoxHost.id.asc())
        .all()
    )
    synced = 0
    for host in hosts:
        if host.last_sync_at and host.last_sync_at >= window_start:
            continue
        try:
            count = sync_host_guests(db, host)
            synced += 1
            logger.info(
                "Schedule pre-sync host %s (%s): %s guests",
                host.name,
                host.id,
                count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Schedule pre-sync failed for host %s (%s)",
                host.name,
                host.id,
            )
            host.last_error = f"Schedule pre-sync failed: {exc}"
            db.commit()
    return synced


def _wants_notification(status: str, *, on_success: bool, on_failure: bool) -> bool:
    if status == "success":
        return on_success
    if status == "failed":
        return on_failure
    return False


async def _email_run(db: Session, run: RestoreRun, settings, ctx: dict) -> None:
    if not _wants_notification(
        run.status,
        on_success=settings.notify_on_success,
        on_failure=settings.notify_on_failure,
    ):
        return
    to_addrs = parse_addr_list(settings.notify_to)
    if not to_addrs:
        return
    cc_addrs = parse_addr_list(settings.notify_cc)
    if run.status == "success":
        subject = Template(settings.email_success_subject).render(**ctx)
        body = Template(settings.email_success_body).render(**ctx)
    else:
        subject = Template(settings.email_failure_subject).render(**ctx)
        body = Template(settings.email_failure_body).render(**ctx)
    inline_images = []
    shot = screenshot_attachment(run)
    if shot:
        inline_images.append(shot)
    try:
        await send_email(
            db,
            to_addrs=to_addrs,
            subject=subject,
            body=body,
            cc_addrs=cc_addrs,
            inline_images=inline_images or None,
        )
        _log(run, "Notification email sent")
    except Exception as exc:  # noqa: BLE001
        _log(run, f"Email failed: {exc}")
        logger.exception("email failed")


async def _push_run(db: Session, run: RestoreRun, ctx: dict) -> None:
    push = get_push_settings(db)
    if not push.enabled or not push.url.strip():
        return
    if not _wants_notification(
        run.status, on_success=push.on_success, on_failure=push.on_failure
    ):
        return
    try:
        await send_push(db, **build_run_push(run, ctx))
        _log(run, "Push notification sent")
    except Exception as exc:  # noqa: BLE001
        _log(run, f"Push failed: {exc}")
        logger.exception("push failed")


async def notify_run(db: Session, run: RestoreRun) -> None:
    # A skipped run means no backup was expected — never alert on it.
    if run.status == "skipped":
        return
    settings = get_app_settings(db)
    app_url = get_settings().app_base_url.rstrip("/")
    ctx = build_notification_context(run, app_url)
    # Each channel decides independently, and neither can break the other.
    await _email_run(db, run, settings, ctx)
    await _push_run(db, run, ctx)
    db.commit()


def execute_restore_run(db: Session, run_id: int) -> None:
    """Synchronous restore pipeline (called from worker)."""
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run:
        return

    # The guest can be deleted from Proxmox (and pruned by sync) between queueing
    # and execution. Cancel rather than burn a lock on a doomed restore.
    queued_guest = db.query(Guest).filter_by(id=run.guest_id).first() if run.guest_id else None
    if queued_guest is None:
        run.status = "skipped"
        run.error_message = (
            f"VMID {run.source_vmid} ({run.source_name}) is no longer in inventory — "
            "restore test skipped"
        )
        run.progress_label = "Skipped"
        run.progress_pct = 100.0
        run.finished_at = datetime.now(timezone.utc)
        _log(run, "Run skipped: guest no longer exists on Proxmox")
        db.commit()
        return

    holder = f"worker-{uuid.uuid4().hex[:8]}"
    if not locks.try_acquire(db, holder, run_id):
        run.status = "failed"
        run.error_message = "Global restore lock is busy; try again later"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    _set_progress(db, run, pct=2.0, label="Starting restore test")
    _log(run, "Acquired global lock")
    db.commit()

    host: Optional[ProxmoxHost] = None
    guest: Optional[Guest] = None
    client: Optional[ProxmoxClient] = None
    test_vmid: Optional[int] = None
    storage: Optional[str] = None
    node = ""
    guest_type = run.guest_type

    try:
        guest = db.query(Guest).filter_by(id=run.guest_id).first() if run.guest_id else None
        host = db.query(ProxmoxHost).filter_by(id=run.host_id).first() if run.host_id else None
        if not guest or not host:
            raise RuntimeError("Guest or host missing for run")

        node = guest.node
        guest_type = guest.guest_type
        run.source_name = guest.name
        run.source_vmid = guest.vmid
        run.guest_type = guest_type
        db.commit()

        client = _client_for_host(host)
        _set_progress(db, run, pct=5.0, label="Connected — validating backup")
        _log(run, f"Connected to Proxmox API for host {host.name}")
        db.commit()

        preflight = preflight_restore_check(db, guest, host, client=client)
        if not preflight.ok:
            if preflight.skip:
                # No backup was expected, so no restore was expected: record it as
                # skipped rather than a failure, and send no notification.
                run.status = "skipped"
                run.error_message = preflight.reason
                run.progress_label = "Skipped"
                run.progress_pct = 100.0
                run.finished_at = datetime.now(timezone.utc)
                _log(run, f"Run skipped: {preflight.reason}")
                db.commit()
                return  # `finally` releases the global lock
            raise RuntimeError(preflight.reason)
        _log(run, "Pre-flight OK: guest present, in a backup job, snapshot available")
        node = guest.node

        backups = client.find_pbs_backups(node, guest.vmid)
        if not backups:
            raise RuntimeError(f"No PBS backups found for VMID {guest.vmid} on node {node}")

        total_backups = len(backups)
        latest_volid = str(backups[0].get("volid") or "")
        run.backup_count = total_backups
        run.latest_backup_volid = latest_volid
        run.used_fallback_backup = False
        run.backups_attempted = 0
        run.backup_used_index = None
        run.result_summary = ""
        _log(
            run,
            f"Found {total_backups} PBS backup(s) for VMID {guest.vmid} (newest first):\n"
            f"{format_backup_inventory(backups)}",
        )
        db.commit()

        test_vmid = pick_test_vmid(client, host)
        run.test_vmid = test_vmid
        _set_progress(db, run, pct=10.0, label=f"Allocated test VMID {test_vmid}")
        _log(run, f"Allocated test VMID {test_vmid}")
        db.commit()

        ssh_ready = bool(host.ssh_host and host.ssh_private_key_path)
        source_hostdevs: list[str] = []
        source_bind_mounts: list[str] = []
        source_cfg: dict = {}
        try:
            if guest_type == "qemu":
                source_cfg = client.qemu_config(node, guest.vmid)
                source_hostdevs = qemu_hostdev_keys(source_cfg)
            else:
                source_cfg = client.lxc_config(node, guest.vmid)
                source_bind_mounts = lxc_host_mount_keys(source_cfg)
        except Exception as exc:  # noqa: BLE001
            _log(run, f"Could not inspect source config for host devices/mounts: {exc}")

        if source_bind_mounts:
            _log(
                run,
                f"Source CT has host bind/device mounts ({', '.join(source_bind_mounts)}); "
                "API tokens cannot restore those — will use SSH pct restore when available",
            )

        storage_hint = storage_hint_from_guest_config(source_cfg, guest_type) if source_cfg else None
        storage = pick_restore_storage(
            client,
            host,
            node,
            storage_hint or host.preferred_restore_storage or "",
            guest_type=guest_type,
        )
        if not storage:
            raise RuntimeError(
                f"No restore storage on node {node} with content type "
                f"{'images' if guest_type == 'qemu' else 'rootdir'}"
            )
        if storage_hint and storage == storage_hint:
            _log(run, f"Restore storage: {storage} (from source guest disks)")
        else:
            _log(run, f"Restore storage: {storage}")
        db.commit()

        def _open_ssh() -> SSHSession:
            if not ssh_ready:
                raise RuntimeError(
                    "SSH is required to restore guests with host USB/PCI passthrough "
                    "or CT bind/device mounts (API tokens cannot apply those). "
                    "Configure SSH on the host."
                )
            return SSHSession(
                host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
            )

        def _cleanup_partial() -> None:
            try:
                ssh_tmp = None
                if ssh_ready:
                    try:
                        ssh_tmp = SSHSession(
                            host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
                        )
                        ssh_tmp.__enter__()
                    except Exception:  # noqa: BLE001
                        ssh_tmp = None
                try:
                    cleanup_test_guest(client, guest_type, node, int(test_vmid), ssh=ssh_tmp)
                finally:
                    if ssh_tmp is not None:
                        try:
                            ssh_tmp.__exit__(None, None, None)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as cleanup_exc:  # noqa: BLE001
                _log(run, f"Partial cleanup of test VMID {test_vmid}: {cleanup_exc}")

        def _manual_restore_cmd(archive_vol: str) -> str:
            if guest_type == "qemu":
                return SSHSession.format_qmrestore_cmd(
                    str(archive_vol), int(test_vmid), storage=storage, unique=True
                )
            return SSHSession.format_pct_restore_cmd(
                str(archive_vol), int(test_vmid), storage=storage, unique=True
            )

        def _log_manual_cmd(archive_vol: str, *, via: str) -> None:
            cmd = _manual_restore_cmd(archive_vol)
            _log(
                run,
                f"Restore command ({via}) — run on Proxmox node {node} as root to troubleshoot:\n"
                f"  {cmd}",
            )

        def _restore_qemu_via_ssh(archive_vol: str, reason: str) -> None:
            _log(run, reason)
            _log_manual_cmd(archive_vol, via="SSH qmrestore")
            _set_progress(
                db,
                run,
                pct=12.0,
                label="Restoring via SSH (USB/PCI passthrough)…",
                node=node,
            )
            db.commit()
            with _open_ssh() as ssh:
                out = ssh.qmrestore(str(archive_vol), int(test_vmid), storage=storage, unique=True)
            if out:
                tail = out[-500:] if len(out) > 500 else out
                _log(run, f"SSH qmrestore finished: {tail}")

        def _restore_lxc_via_ssh(archive_vol: str, reason: str) -> None:
            _log(run, reason)
            _log_manual_cmd(archive_vol, via="SSH pct restore")
            _set_progress(
                db,
                run,
                pct=12.0,
                label="Restoring via SSH (CT bind mounts)…",
                node=node,
            )
            db.commit()
            with _open_ssh() as ssh:
                out = ssh.pct_restore(str(archive_vol), int(test_vmid), storage=storage, unique=True)
            if out:
                tail = out[-500:] if len(out) > 500 else out
                _log(run, f"SSH pct restore finished: {tail}")

        def _restore_via_api(archive_vol: str) -> None:
            nonlocal last_logged_pct, last_heartbeat_log
            _log_manual_cmd(archive_vol, via="API (CLI equivalent)")
            if guest_type == "qemu":
                upid = client.restore_qemu(
                    node, test_vmid, archive_vol, storage=storage, unique=True, start=False
                )
            else:
                upid = client.restore_lxc(
                    node, test_vmid, archive_vol, storage=storage, unique=True, start=False
                )
            _set_progress(
                db,
                run,
                pct=12.0,
                label="Restoring from PBS…",
                upid=str(upid),
                node=node,
            )
            _log(run, f"Restore started: {upid}")
            db.commit()

            def _restore_progress(status: dict) -> None:
                nonlocal last_logged_pct, last_heartbeat_log
                prox_pct = client.task_progress_pct(node, str(upid), status=status)
                if prox_pct is not None:
                    pct = 12.0 + (prox_pct * 0.68)
                    _set_progress(
                        db,
                        run,
                        pct=pct,
                        label=f"Restoring from PBS… {round(prox_pct)}% on Proxmox",
                    )
                    rounded = round(pct)
                    if last_logged_pct is None or abs(rounded - (last_logged_pct or 0)) >= 5:
                        _log(
                            run,
                            f"Restore progress ~{rounded}% (Proxmox reported {round(prox_pct)}%)",
                        )
                        last_logged_pct = float(rounded)
                else:
                    _set_progress(
                        db,
                        run,
                        pct=None,
                        label="Restoring from PBS… (Proxmox transferring data; no % yet)",
                    )
                    now = time.time()
                    if now - last_heartbeat_log >= 60:
                        task_st = (status or {}).get("status") or "running"
                        _log(
                            run,
                            f"Restore still running on Proxmox (task {task_st}; "
                            "no percentage reported — large disk transfers can take a while)",
                        )
                        last_heartbeat_log = now
                db.commit()

            client.wait_task(
                node, upid, timeout=7200, on_poll=_restore_progress, on_poll_every=5.0
            )

        if guest_type == "qemu" and source_hostdevs and not ssh_ready:
            raise RuntimeError(
                f"Source VM has host passthrough devices ({', '.join(source_hostdevs)}). "
                "API tokens cannot restore those configs. Install the RestoreProof SSH key "
                "on the Proxmox host and Test SSH, then retry — or exclude this guest."
            )
        if guest_type != "qemu" and source_bind_mounts and not ssh_ready:
            raise RuntimeError(
                f"Source CT has host bind/device mounts ({', '.join(source_bind_mounts)}). "
                "API tokens cannot restore bind mounts (Proxmox root-only restriction). "
                "Install the RestoreProof SSH key on the Proxmox host and Test SSH, "
                "then retry — or exclude this guest."
            )

        last_logged_pct: Optional[float] = None
        last_heartbeat_log = 0.0
        last_backup_error: Optional[BaseException] = None
        restored_ok = False
        restore_method = "API"
        failed_newer: list[tuple[str, str]] = []
        used_idx: Optional[int] = None
        max_try = min(5, total_backups)

        # Try newest backups first; fall through to older snapshots on snapshot-specific failures
        for idx, backup in enumerate(backups[:max_try]):
            archive = str(backup.get("volid") or "")
            if not archive:
                continue
            attempt_num = idx + 1
            run.backup_volid = archive
            run.backup_used_index = attempt_num
            run.backups_attempted = attempt_num
            run.used_fallback_backup = attempt_num > 1
            if attempt_num == 1:
                _set_progress(
                    db,
                    run,
                    pct=8.0,
                    label=f"Trying latest backup (1 of {total_backups} available)",
                )
                _log(
                    run,
                    f"Trying LATEST backup (1 of {total_backups} available): {archive}",
                )
            else:
                _set_progress(
                    db,
                    run,
                    pct=8.0,
                    label=f"⚠ Older backup {attempt_num}/{total_backups} (latest failed)",
                )
                _log(
                    run,
                    f"⚠ NOT THE LATEST — trying backup {attempt_num} of {total_backups} "
                    f"(newer snapshot(s) failed): {archive}",
                )
            db.commit()

            try:
                if guest_type == "qemu" and source_hostdevs and ssh_ready:
                    restore_method = "SSH qmrestore (host USB/PCI passthrough)"
                    _restore_qemu_via_ssh(
                        archive,
                        f"Source has host passthrough ({', '.join(source_hostdevs)}); "
                        "restoring via SSH as root so API token USB restrictions are avoided",
                    )
                elif guest_type != "qemu" and source_bind_mounts and ssh_ready:
                    restore_method = "SSH pct restore (CT bind/device mounts)"
                    _restore_lxc_via_ssh(
                        archive,
                        f"Source has bind/device mounts ({', '.join(source_bind_mounts)}); "
                        "restoring via SSH as root (API tokens cannot restore bind mounts)",
                    )
                else:
                    try:
                        restore_method = "API"
                        _restore_via_api(archive)
                    except ProxmoxAPIError as api_exc:
                        if guest_type == "qemu" and is_hostdev_privilege_error(api_exc) and ssh_ready:
                            _cleanup_partial()
                            restore_method = "SSH qmrestore (API hostdev fallback)"
                            _restore_qemu_via_ssh(
                                archive,
                                f"API restore blocked by host USB/PCI ({api_exc}); "
                                "retrying via SSH as root",
                            )
                        elif guest_type == "qemu" and is_hostdev_privilege_error(api_exc):
                            raise RuntimeError(
                                f"{api_exc} — API tokens cannot restore guests with host USB/PCI "
                                "passthrough. Configure SSH on this host (or exclude the guest)."
                            ) from api_exc
                        elif (
                            guest_type != "qemu"
                            and is_lxc_mount_privilege_error(api_exc)
                            and ssh_ready
                        ):
                            _cleanup_partial()
                            restore_method = "SSH pct restore (API bind-mount fallback)"
                            _restore_lxc_via_ssh(
                                archive,
                                f"API restore blocked by CT bind/device mount ({api_exc}); "
                                "retrying via SSH as root",
                            )
                        elif guest_type != "qemu" and is_lxc_mount_privilege_error(api_exc):
                            raise RuntimeError(
                                f"{api_exc} — API tokens cannot restore CTs with host bind/device "
                                "mounts. Configure SSH on this host (or exclude the guest)."
                            ) from api_exc
                        else:
                            raise
                restored_ok = True
                used_idx = attempt_num
                run.used_fallback_backup = attempt_num > 1
                run.backup_used_index = attempt_num
                if attempt_num > 1:
                    _set_progress(
                        db,
                        run,
                        pct=82.0,
                        label=f"⚠ Restored older backup #{attempt_num}/{total_backups}",
                    )
                    _log(
                        run,
                        f"⚠ Restore succeeded using OLDER backup #{attempt_num} of {total_backups} "
                        f"— NOT the latest. Latest was: {latest_volid}",
                    )
                else:
                    _set_progress(db, run, pct=82.0, label="Restore finished — configuring")
                    _log(run, "Restore completed using the latest backup")
                db.commit()
                break
            except Exception as bak_exc:  # noqa: BLE001
                last_backup_error = bak_exc
                failed_newer.append((archive, str(bak_exc)))
                _log(
                    run,
                    f"Restore failed for this snapshot. Manual retry on node {node} as root:\n"
                    f"  {_manual_restore_cmd(archive)}",
                )
                if should_try_older_backup(bak_exc) and attempt_num < max_try:
                    why = (
                        "incomplete/corrupt on PBS"
                        if is_pbs_data_error(bak_exc)
                        else "restore failed"
                    )
                    _log(
                        run,
                        f"Backup {attempt_num} of {total_backups} {why}. "
                        f"Falling back to next-older snapshot "
                        f"({attempt_num + 1} of {total_backups})…",
                    )
                    _cleanup_partial()
                    db.commit()
                    continue
                run.result_summary = build_env_diagnostics(
                    host=host,
                    guest=guest,
                    node=node,
                    guest_type=guest_type,
                    test_vmid=test_vmid,
                    storage=storage,
                    backups=backups,
                    latest_volid=latest_volid,
                    used_volid=archive,
                    used_index=attempt_num,
                    attempted=attempt_num,
                    used_fallback=attempt_num > 1,
                    restore_method=restore_method,
                    source_hostdevs=source_hostdevs,
                    source_bind_mounts=source_bind_mounts,
                    ssh_ready=ssh_ready,
                    failed_newer=failed_newer,
                    manual_cmd=_manual_restore_cmd(archive),
                    success=False,
                )
                _log(run, "—— Failure diagnostics ——\n" + run.result_summary)
                db.commit()
                raise

        if not restored_ok:
            err = last_backup_error or RuntimeError("No usable PBS backup could be restored")
            summary = build_env_diagnostics(
                host=host,
                guest=guest,
                node=node,
                guest_type=guest_type,
                test_vmid=test_vmid,
                storage=storage,
                backups=backups,
                latest_volid=latest_volid,
                used_volid=str(run.backup_volid or ""),
                used_index=run.backup_used_index,
                attempted=run.backups_attempted,
                used_fallback=bool(run.used_fallback_backup),
                restore_method=restore_method,
                source_hostdevs=source_hostdevs,
                source_bind_mounts=source_bind_mounts,
                ssh_ready=ssh_ready,
                failed_newer=failed_newer,
                manual_cmd=_manual_restore_cmd(str(run.backup_volid or latest_volid)),
                success=False,
            )
            run.result_summary = summary
            _log(run, "—— Failure diagnostics ——\n" + summary)
            db.commit()
            if is_pbs_data_error(err):
                raise RuntimeError(
                    f"PBS backup data error for VMID {guest.vmid} "
                    f"(tried {run.backups_attempted} of {total_backups} available). "
                    f"{err}. "
                    "The snapshot(s) may be incomplete (missing chunk). "
                    "Verify in PBS, take a fresh backup, then retry."
                ) from err
            raise err

        # Success diagnostics (especially important when not using latest)
        run.result_summary = build_env_diagnostics(
            host=host,
            guest=guest,
            node=node,
            guest_type=guest_type,
            test_vmid=test_vmid,
            storage=storage,
            backups=backups,
            latest_volid=latest_volid,
            used_volid=str(run.backup_volid or ""),
            used_index=used_idx,
            attempted=run.backups_attempted,
            used_fallback=bool(run.used_fallback_backup),
            restore_method=restore_method,
            source_hostdevs=source_hostdevs,
            source_bind_mounts=source_bind_mounts,
            ssh_ready=ssh_ready,
            failed_newer=failed_newer,
            manual_cmd="",
            success=True,
        )
        if run.used_fallback_backup:
            _log(
                run,
                "—— IMPORTANT: older backup was used ——\n" + run.result_summary,
            )
        else:
            _log(run, "—— Restore diagnostics ——\n" + run.result_summary)
        db.commit()

        # Detach NICs (and host USB/PCI / CT bind mounts) before start — test guests stay isolated
        if guest_type == "qemu":
            deleted: list[str] = []
            try:
                deleted = client.qemu_unlink_nets(node, test_vmid)
                deleted += client.qemu_unlink_hostdevs(node, test_vmid)
            except ProxmoxAPIError as unlink_exc:
                if ssh_ready:
                    _log(run, f"API unlink failed ({unlink_exc}); trying SSH qm set --delete")
                    cfg = client.qemu_config(node, test_vmid)
                    keys = [k for k in cfg.keys() if str(k).startswith("net")] + qemu_hostdev_keys(
                        cfg
                    )
                    with _open_ssh() as ssh:
                        deleted = ssh.qm_delete_keys(int(test_vmid), keys)
                else:
                    raise
        else:
            deleted = client.lxc_unlink_nets(node, test_vmid)
            cfg_pre = client.lxc_config(node, test_vmid)
            bind_keys = lxc_host_mount_keys(cfg_pre)
            if bind_keys:
                # Tokens usually cannot delete bind mounts either — prefer SSH as root.
                if ssh_ready:
                    _log(
                        run,
                        f"Removing restored bind/device mounts from test CT "
                        f"({', '.join(bind_keys)}) so drills do not remount host paths",
                    )
                    with _open_ssh() as ssh:
                        deleted += ssh.pct_delete_keys(int(test_vmid), bind_keys)
                else:
                    try:
                        client.lxc_set_config(node, test_vmid, delete=",".join(sorted(bind_keys)))
                        deleted += bind_keys
                    except ProxmoxAPIError as unlink_exc:
                        raise RuntimeError(
                            f"Could not detach CT bind mounts {bind_keys}: {unlink_exc}. "
                            "Configure SSH so RestoreProof can remove them as root."
                        ) from unlink_exc
        _set_progress(db, run, pct=86.0, label="Detached NICs — starting guest")
        _log(run, f"Detached NICs/hostdevs/mounts: {deleted or 'none'}")
        cfg = (
            client.qemu_config(node, test_vmid)
            if guest_type == "qemu"
            else client.lxc_config(node, test_vmid)
        )
        leftover_nets = [k for k in cfg.keys() if str(k).startswith("net")]
        leftover_host = (
            qemu_hostdev_keys(cfg) if guest_type == "qemu" else lxc_host_mount_keys(cfg)
        )
        if leftover_nets or leftover_host:
            raise RuntimeError(
                f"Detach incomplete; still present: {leftover_nets + leftover_host}"
            )
        # Source backups often copy protection: 1, which blocks destroy later.
        try:
            if client.clear_guest_protection(node, test_vmid, guest_type):
                _log(run, "Cleared protection on test guest (copied from source backup)")
        except ProxmoxAPIError as prot_exc:
            if ssh_ready:
                _log(run, f"API could not clear protection ({prot_exc}); trying SSH")
                with _open_ssh() as ssh:
                    ssh.clear_protection(guest_type, int(test_vmid))
                _log(run, "Cleared protection via SSH")
            else:
                _log(run, f"Warning: could not clear protection: {prot_exc}")
        db.commit()

        if guest_type == "qemu":
            upid = client.qemu_start(node, test_vmid)
        else:
            upid = client.lxc_start(node, test_vmid)
        start_status = client.wait_task(node, upid, timeout=300)
        start_exit = str(start_status.get("exitstatus") or "OK")
        if is_successful_task_exit(start_exit) and start_exit.upper().startswith("WARNING"):
            warn_bits: list[str] = []
            try:
                for entry in client.task_log(node, str(upid), start=0, limit=80):
                    text = str(entry.get("t") or entry.get("text") or "").strip()
                    if text.upper().startswith("WARN"):
                        warn_bits.append(text)
            except Exception:  # noqa: BLE001
                pass
            detail = " ".join(warn_bits) if warn_bits else start_exit
            if len(detail) > 400:
                detail = detail[:397] + "…"
            _log(
                run,
                f"Guest started with Proxmox warning(s) ({start_exit}) — "
                f"treating as success. {detail}",
            )
        else:
            _log(run, "Guest started")
        _set_progress(db, run, pct=90.0, label="Guest started — waiting for boot")
        db.commit()

        app_settings = get_app_settings(db)
        wait_s = app_settings.boot_wait_seconds or get_settings().default_boot_wait_seconds
        _log(run, f"Waiting {wait_s}s for boot")
        db.commit()
        time.sleep(wait_s)

        _set_progress(db, run, pct=93.0, label="Capturing evidence")
        db.commit()

        evidence_dir = Path(get_settings().data_dir) / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        if guest_type == "qemu":
            if not host.ssh_host or not host.ssh_private_key_path:
                raise RuntimeError("SSH host/key required for VM console screenshots")
            # PVE QEMU often lacks libpng — dump PPM, convert to PNG in-app for UI/email
            remote = f"/tmp/restoreproof-{test_vmid}.ppm"
            local_raw = evidence_dir / f"run_{run.id}.ppm"
            local = evidence_dir / f"run_{run.id}.png"
            with SSHSession(
                host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
            ) as ssh:
                ssh.screendump_vm(test_vmid, remote)
                ssh.fetch_file(remote, str(local_raw))
            convert_screendump_to_png(local_raw, local)
            local_raw.unlink(missing_ok=True)
            run.evidence_path = str(local)
            run.evidence_kind = "screenshot"
            _log(run, f"Screenshot saved to {local} (converted from QEMU PPM screendump)")
        else:
            status = client.lxc_status(node, test_vmid)
            proof = {
                "type": "container_proof",
                "vmid": test_vmid,
                "status": status.get("status"),
                "uptime": status.get("uptime"),
                "name": status.get("name"),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            local = evidence_dir / f"run_{run.id}.json"
            local.write_text(json.dumps(proof, indent=2))
            run.evidence_path = str(local)
            run.evidence_kind = "container_proof"
            run.evidence_json = json.dumps(proof)
            _log(run, f"Container proof saved: {proof}")
        db.commit()

        _set_progress(db, run, pct=97.0, label="Cleaning up test guest")
        run.status = "success"
        guest.last_tested_at = datetime.now(timezone.utc)
        if run.used_fallback_backup:
            _log(
                run,
                f"Restore test SUCCESS — but used OLDER backup "
                f"#{run.backup_used_index} of {run.backup_count} (not the latest)",
            )
        else:
            _log(run, "Restore test SUCCESS")
        db.commit()

    except Exception as exc:  # noqa: BLE001
        logger.exception("restore run %s failed", run_id)
        msg = str(exc)
        if "only root can set" in msg.lower() and ("usb" in msg.lower() or "hostpci" in msg.lower()):
            msg = (
                f"{msg} — API tokens cannot restore guests that pass through host USB/PCI devices. "
                "Exclude this guest, or remove those host devices from the source before the next backup."
            )
        elif is_lxc_mount_privilege_error(exc):
            msg = (
                f"{msg} — API tokens cannot restore CTs with host bind/device mounts. "
                "Install the RestoreProof SSH key on the Proxmox host, run Test SSH, and retry "
                "(or exclude this guest)."
            )
        elif is_pbs_data_error(exc) and "PBS backup data error" not in msg:
            msg = (
                f"{msg} — PBS snapshot data looks incomplete (missing chunk). "
                "Verify this backup in PBS or take a fresh backup, then retry."
            )
        if run.backup_count:
            msg = (
                f"{msg}\n"
                f"(PBS backups available for this guest: {run.backup_count}; "
                f"attempted: {run.backups_attempted or 0})"
            )
        run.status = "failed"
        run.error_message = msg
        _set_progress(db, run, label="Failed")
        _log(run, f"ERROR: {msg}")
        if run.backup_volid and test_vmid and storage and node:
            if (guest_type or "qemu") == "qemu":
                fail_cmd = SSHSession.format_qmrestore_cmd(
                    str(run.backup_volid), int(test_vmid), storage=storage, unique=True
                )
            else:
                fail_cmd = SSHSession.format_pct_restore_cmd(
                    str(run.backup_volid), int(test_vmid), storage=storage, unique=True
                )
            _log(
                run,
                f"Manual retry on Proxmox node {node} as root:\n  {fail_cmd}",
            )
        if run.result_summary:
            _log(run, "See result_summary / diagnostics above for backup inventory and environment.")
        db.commit()
    finally:
        try:
            if client and host and test_vmid and node:
                if run.status == "success":
                    _set_progress(db, run, pct=97.0, label="Cleaning up test guest")
                _log(run, f"Cleaning up test guest {test_vmid}")
                db.commit()
                try:
                    ssh = None
                    if host.ssh_host and host.ssh_private_key_path:
                        try:
                            ssh = SSHSession(
                                host.ssh_host,
                                host.ssh_port,
                                host.ssh_user,
                                host.ssh_private_key_path,
                            )
                            ssh.__enter__()
                        except Exception:  # noqa: BLE001
                            ssh = None
                    try:
                        msg = cleanup_test_guest(
                            client, guest_type, node, int(test_vmid), ssh=ssh
                        )
                        _log(run, f"Cleanup complete ({msg})")
                    finally:
                        if ssh is not None:
                            try:
                                ssh.__exit__(None, None, None)
                            except Exception:  # noqa: BLE001
                                pass
                except ProxmoxAPIError as cleanup_exc:
                    _log(run, f"Cleanup warning: {cleanup_exc}")
        except Exception as cleanup_exc:  # noqa: BLE001
            _log(run, f"Cleanup error: {cleanup_exc}")
        if run.status == "success":
            _set_progress(db, run, pct=100.0, label="Complete")
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        locks.release(db, holder)

    try:
        asyncio.run(notify_run(db, run))
    except Exception:  # noqa: BLE001
        logger.exception("notify failed")
