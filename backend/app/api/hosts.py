"""
Purpose: Proxmox host connection management + SSH key exchange helpers.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-27
Version: 1.4.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from shlex import quote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ProxmoxHost, RestoreRun, User
from app.schemas import HostCreate, HostLatestRunOut, HostOut, HostUpdate
from app.security import decrypt_secret, encrypt_secret
from app.services.proxmox import ProxmoxAPIError, ProxmoxClient
from app.services.restore import sync_host_guests
from app.services.ssh_keys import generate_host_ssh_key, read_public_key

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _latest_run_for_host(db: Session, host_id: int) -> HostLatestRunOut | None:
    run = (
        db.query(RestoreRun)
        .filter(
            RestoreRun.host_id == host_id,
            RestoreRun.status.in_(("success", "failed")),
        )
        .order_by(RestoreRun.finished_at.desc().nullslast(), RestoreRun.id.desc())
        .first()
    )
    if not run:
        return None
    return HostLatestRunOut(
        id=run.id,
        status=run.status,
        source_name=run.source_name,
        source_vmid=run.source_vmid,
        guest_type=run.guest_type,
        evidence_kind=run.evidence_kind or "none",
        error_message=run.error_message,
        result_summary=run.result_summary or None,
        used_fallback_backup=bool(run.used_fallback_backup),
        backup_count=run.backup_count,
        backup_used_index=run.backup_used_index,
        finished_at=run.finished_at,
        started_at=run.started_at,
    )


def _host_out(db: Session, host: ProxmoxHost) -> HostOut:
    return HostOut(
        id=host.id,
        name=host.name,
        api_url=host.api_url,
        token_id=host.token_id,
        verify_ssl=host.verify_ssl,
        ssh_host=host.ssh_host,
        ssh_port=host.ssh_port,
        ssh_user=host.ssh_user,
        ssh_private_key_path=host.ssh_private_key_path,
        preferred_restore_storage=host.preferred_restore_storage,
        test_vmid_start=host.test_vmid_start,
        test_vmid_end=host.test_vmid_end,
        enabled=host.enabled,
        last_sync_at=host.last_sync_at,
        api_ok_at=host.api_ok_at,
        ssh_ok_at=host.ssh_ok_at,
        last_error=host.last_error,
        has_token_secret=bool(host.token_secret_enc),
        has_ssh_key=bool(host.ssh_private_key_path),
        latest_run=_latest_run_for_host(db, host.id),
    )


def _ssh_install_command(host: ProxmoxHost, public_key: str) -> str:
    """One-liner run from an admin machine to install the public key on Proxmox."""
    target = f"{host.ssh_user}@{host.ssh_host or '<proxmox-host>'}"
    port_part = f"-p {host.ssh_port} " if host.ssh_port and host.ssh_port != 22 else ""
    remote = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"echo {quote(public_key)} >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )
    return f"ssh {port_part}{target} {quote(remote)}"


@router.get("", response_model=list[HostOut])
def list_hosts(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list:
    return [_host_out(db, h) for h in db.query(ProxmoxHost).order_by(ProxmoxHost.id).all()]


@router.post("", response_model=HostOut)
def create_host(
    body: HostCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> HostOut:
    host = ProxmoxHost(
        name=body.name,
        api_url=body.api_url,
        token_id=body.token_id,
        token_secret_enc=encrypt_secret(body.token_secret),
        verify_ssl=body.verify_ssl,
        ssh_host=body.ssh_host or "",
        ssh_port=body.ssh_port,
        ssh_user=body.ssh_user,
        preferred_restore_storage=body.preferred_restore_storage,
        test_vmid_start=body.test_vmid_start,
        test_vmid_end=body.test_vmid_end,
        enabled=body.enabled,
    )
    db.add(host)
    db.commit()
    db.refresh(host)
    private_path, _pub = generate_host_ssh_key(host.id)
    host.ssh_private_key_path = private_path
    if not host.ssh_host:
        # default SSH host from API URL hostname
        try:
            from urllib.parse import urlparse

            host.ssh_host = urlparse(host.api_url).hostname or ""
        except Exception:  # noqa: BLE001
            pass
    db.commit()
    db.refresh(host)
    return _host_out(db, host)


@router.get("/{host_id}", response_model=HostOut)
def get_host(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> HostOut:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    return _host_out(db, host)


@router.put("/{host_id}", response_model=HostOut)
def update_host(
    host_id: int,
    body: HostUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> HostOut:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    data = body.model_dump(exclude_unset=True)
    secret = data.pop("token_secret", None)
    for key, value in data.items():
        setattr(host, key, value)
    if secret:
        host.token_secret_enc = encrypt_secret(secret)
        host.api_ok_at = None
    db.commit()
    db.refresh(host)
    return _host_out(db, host)


@router.delete("/{host_id}")
def delete_host(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    db.delete(host)
    db.commit()
    return {"ok": True}


@router.post("/{host_id}/test-api")
def test_api(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    try:
        client = ProxmoxClient(
            host.api_url,
            host.token_id,
            decrypt_secret(host.token_secret_enc),
            verify_ssl=host.verify_ssl,
        )
        version = client.version()
        nodes = client.nodes()
        storages = client.storage_list()
        host.last_error = None
        host.api_ok_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "ok": True,
            "version": version,
            "nodes": [n.get("node") for n in nodes],
            "storages": [
                {
                    "storage": s.get("storage"),
                    "type": s.get("type"),
                    "content": s.get("content"),
                }
                for s in storages
            ],
        }
    except ValueError as exc:
        host.last_error = str(exc)
        host.api_ok_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProxmoxAPIError as exc:
        host.last_error = str(exc)
        host.api_ok_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{host_id}/sync")
def sync_guests(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    try:
        count = sync_host_guests(db, host)
        return {"ok": True, "synced": count}
    except Exception as exc:  # noqa: BLE001
        host.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{host_id}/ssh-key")
def get_ssh_public_key(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    if not host.ssh_private_key_path:
        path, pub = generate_host_ssh_key(host.id)
        host.ssh_private_key_path = path
        db.commit()
    else:
        pub = read_public_key(host.id)
        if not pub:
            path, pub = generate_host_ssh_key(host.id)
            host.ssh_private_key_path = path
            db.commit()
    install_cmd = _ssh_install_command(host, pub)
    return {
        "public_key": pub,
        "install_command": install_cmd,
        "instructions": (
            "Run the install command from your admin machine (Mac/PC) to append this public key "
            f"to authorized_keys on {host.ssh_user}@{host.ssh_host or '<ssh_host>'}. "
            "One node is enough for a cluster. RestoreProof SSHes in there, then uses the "
            "cluster's own root SSH to run screendump and qm/pct on the node that owns the guest. "
            "Add the cluster once — a second host pointed at the same API copies the inventory "
            "and backup mappings break."
        ),
    }


@router.post("/{host_id}/test-ssh")
def test_ssh(
    host_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    host = db.query(ProxmoxHost).filter_by(id=host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    if not host.ssh_host or not host.ssh_private_key_path:
        raise HTTPException(status_code=400, detail="SSH host or key not configured")
    from app.services.ssh_keys import SSHSession

    try:
        with SSHSession(
            host.ssh_host, host.ssh_port, host.ssh_user, host.ssh_private_key_path
        ) as ssh:
            code, out, err = ssh.run("hostname && pveversion | head -1")
            if code != 0:
                raise RuntimeError(err or out)
            host.ssh_ok_at = datetime.now(timezone.utc)
            host.last_error = None
            db.commit()
            return {"ok": True, "output": out.strip()}
    except Exception as exc:  # noqa: BLE001
        host.ssh_ok_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
