"""
Purpose: Full restore → boot → evidence → cleanup cycle for one guest.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.2.1
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
from app.services.bootstrap import get_app_settings
from app.services.mailer import parse_addr_list, send_email
from app.services.proxmox import ProxmoxAPIError, ProxmoxClient
from app.services.ssh_keys import SSHSession

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


def cleanup_test_guest(
    client: ProxmoxClient,
    guest_type: str,
    node: str,
    test_vmid: int,
    ssh: Optional[SSHSession] = None,
) -> str:
    """Stop and destroy a leftover test qemu/lxc guest. Returns a short status message."""
    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
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
            upid = client.lxc_delete(node, test_vmid, purge=True)
            client.wait_task(node, upid, timeout=600)
            return "deleted"
        except ProxmoxAPIError as exc:
            last_err = exc
            msg = str(exc).lower()
            if ("lock" in msg or "timeout" in msg) and ssh is not None and guest_type == "qemu":
                try:
                    ssh.run(f"qm unlock {test_vmid} || true")
                    ssh.run(f"rm -f /var/lock/qemu-server/lock-{test_vmid}.conf")
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2 * attempt)
                continue
            if "lock" in msg or "timeout" in msg:
                time.sleep(3 * attempt)
                continue
            if exc.status_code == 404:
                return "already gone"
            raise
    if last_err:
        raise last_err
    return "failed"


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


def sync_host_guests(db: Session, host: ProxmoxHost) -> int:
    client = _client_for_host(host)
    client.version()
    resources = client.cluster_resources(resource_type="vm")
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
        count += 1

    existing = db.query(Guest).filter(Guest.host_id == host.id).all()
    for g in existing:
        if g.vmid not in seen:
            db.delete(g)

    host.last_sync_at = datetime.now(timezone.utc)
    host.last_error = None
    db.commit()
    return count


async def notify_run(db: Session, run: RestoreRun) -> None:
    settings = get_app_settings(db)
    if run.status == "success" and not settings.notify_on_success:
        return
    if run.status == "failed" and not settings.notify_on_failure:
        return
    to_addrs = parse_addr_list(settings.notify_to)
    if not to_addrs:
        return
    cc_addrs = parse_addr_list(settings.notify_cc)
    app_url = get_settings().app_base_url.rstrip("/")
    ctx = {
        "guest_name": run.source_name,
        "vmid": run.source_vmid,
        "test_vmid": run.test_vmid or "",
        "backup_volid": run.backup_volid,
        "error_message": run.error_message or "",
        "started_at": run.started_at.isoformat() if run.started_at else "",
        "finished_at": run.finished_at.isoformat() if run.finished_at else "",
        "run_url": f"{app_url}/runs/{run.id}",
        "status": run.status,
    }
    if run.status == "success":
        subject = Template(settings.email_success_subject).render(**ctx)
        body = Template(settings.email_success_body).render(**ctx)
    else:
        subject = Template(settings.email_failure_subject).render(**ctx)
        body = Template(settings.email_failure_body).render(**ctx)
    try:
        await send_email(db, to_addrs=to_addrs, subject=subject, body=body, cc_addrs=cc_addrs)
        _log(run, "Notification email sent")
    except Exception as exc:  # noqa: BLE001
        _log(run, f"Email failed: {exc}")
        logger.exception("email failed")
    db.commit()


def execute_restore_run(db: Session, run_id: int) -> None:
    """Synchronous restore pipeline (called from worker)."""
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run:
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
        _set_progress(db, run, pct=5.0, label="Connected — finding backup")
        _log(run, f"Connected to Proxmox API for host {host.name}")
        db.commit()

        backups = client.find_pbs_backups(node, guest.vmid)
        if not backups:
            raise RuntimeError(f"No PBS backups found for VMID {guest.vmid} on node {node}")
        latest = backups[0]
        archive = latest.get("volid")
        run.backup_volid = archive or ""
        _set_progress(db, run, pct=8.0, label="Backup selected")
        _log(run, f"Selected backup {archive}")
        db.commit()

        test_vmid = pick_test_vmid(client, host)
        run.test_vmid = test_vmid
        _set_progress(db, run, pct=10.0, label=f"Allocated test VMID {test_vmid}")
        _log(run, f"Allocated test VMID {test_vmid}")
        db.commit()

        storage = pick_restore_storage(
            client, host, node, host.preferred_restore_storage, guest_type=guest_type
        )
        if not storage:
            raise RuntimeError(
                f"No restore storage on node {node} with content type "
                f"{'images' if guest_type == 'qemu' else 'rootdir'}"
            )
        _log(run, f"Restore storage: {storage}")
        db.commit()

        if guest_type == "qemu":
            upid = client.restore_qemu(
                node, test_vmid, archive, storage=storage, unique=True, start=False
            )
        else:
            upid = client.restore_lxc(
                node, test_vmid, archive, storage=storage, unique=True, start=False
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

        last_logged_pct: Optional[float] = None
        last_heartbeat_log = 0.0

        def _restore_progress(status: dict) -> None:
            nonlocal last_logged_pct, last_heartbeat_log
            prox_pct = client.task_progress_pct(node, str(upid), status=status)
            if prox_pct is not None:
                # Map Proxmox 0–100 into the restore window (12–80)
                pct = 12.0 + (prox_pct * 0.68)
                _set_progress(
                    db,
                    run,
                    pct=pct,
                    label=f"Restoring from PBS… {round(prox_pct)}% on Proxmox",
                )
                rounded = round(pct)
                if last_logged_pct is None or abs(rounded - (last_logged_pct or 0)) >= 5:
                    _log(run, f"Restore progress ~{rounded}% (Proxmox reported {round(prox_pct)}%)")
                    last_logged_pct = float(rounded)
            else:
                # Many vzrestore/qmrestore tasks never expose a percentage while
                # streaming disk data — do not invent a climbing % that caps at 75.
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
        _set_progress(db, run, pct=82.0, label="Restore finished — configuring")
        _log(run, "Restore completed")
        db.commit()

        # Detach NICs (and host USB/PCI) before start — test guests must stay isolated
        if guest_type == "qemu":
            deleted = client.qemu_unlink_nets(node, test_vmid)
            deleted += client.qemu_unlink_hostdevs(node, test_vmid)
        else:
            deleted = client.lxc_unlink_nets(node, test_vmid)
        _set_progress(db, run, pct=86.0, label="Detached NICs — starting guest")
        _log(run, f"Detached NICs/hostdevs: {deleted or 'none'}")
        cfg = (
            client.qemu_config(node, test_vmid)
            if guest_type == "qemu"
            else client.lxc_config(node, test_vmid)
        )
        leftover = [k for k in cfg.keys() if str(k).startswith("net")]
        if leftover:
            raise RuntimeError(f"NIC detach incomplete; still present: {leftover}")
        db.commit()

        if guest_type == "qemu":
            upid = client.qemu_start(node, test_vmid)
        else:
            upid = client.lxc_start(node, test_vmid)
        client.wait_task(node, upid, timeout=300)
        _set_progress(db, run, pct=90.0, label="Guest started — waiting for boot")
        _log(run, "Guest started")
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
            remote = f"/tmp/restoreproof-{test_vmid}.png"
            local = evidence_dir / f"run_{run.id}.png"
            with SSHSession(
                host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
            ) as ssh:
                ssh.screendump_vm(test_vmid, remote)
                ssh.fetch_file(remote, str(local))
            run.evidence_path = str(local)
            run.evidence_kind = "screenshot"
            _log(run, f"Screenshot saved to {local}")
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
        run.status = "failed"
        run.error_message = msg
        _set_progress(db, run, label="Failed")
        _log(run, f"ERROR: {msg}")
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
