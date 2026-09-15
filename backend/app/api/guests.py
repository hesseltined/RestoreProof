"""
Purpose: Guest inventory, exclude/schedule overrides, run-now.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-31
Version: 1.4.0
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Guest, ProxmoxHost, RestoreRun, User
from app.schemas import GuestLatestRunOut, GuestOut, GuestUpdate, RunOut
from app.services.bootstrap import get_app_settings
from app.services.restore import preflight_restore_check
from app.services.scheduler import compute_next_due, refresh_guest_due_times

router = APIRouter(prefix="/guests", tags=["guests"])


def _latest_run_out(run: RestoreRun | None) -> GuestLatestRunOut | None:
    if not run:
        return None
    return GuestLatestRunOut(
        id=run.id,
        status=run.status,
        used_fallback_backup=bool(run.used_fallback_backup),
        finished_at=run.finished_at,
        started_at=run.started_at,
        error_message=run.error_message,
    )


def _latest_runs_by_guest(db: Session) -> dict[int, RestoreRun]:
    """Most recent restore attempt per guest (any status), keyed by guest_id."""
    subq = (
        db.query(
            RestoreRun.guest_id.label("guest_id"),
            func.max(RestoreRun.id).label("max_id"),
        )
        .filter(RestoreRun.guest_id.isnot(None))
        .group_by(RestoreRun.guest_id)
        .subquery()
    )
    rows = db.query(RestoreRun).join(subq, RestoreRun.id == subq.c.max_id).all()
    return {int(r.guest_id): r for r in rows if r.guest_id is not None}


def _guest_out(
    guest: Guest,
    host_name: str = "",
    latest_run: RestoreRun | None = None,
) -> GuestOut:
    return GuestOut(
        id=guest.id,
        host_id=guest.host_id,
        host_name=host_name,
        vmid=guest.vmid,
        name=guest.name,
        guest_type=guest.guest_type,
        node=guest.node,
        status=guest.status,
        cpu_cores=guest.cpu_cores,
        memory_bytes=guest.memory_bytes,
        disk_bytes=guest.disk_bytes,
        excluded=guest.excluded,
        in_backup_job=bool(guest.in_backup_job),
        backup_job_enabled=bool(guest.backup_job_enabled),
        backup_job_summary=guest.backup_job_summary or "",
        backup_snapshot_count=int(guest.backup_snapshot_count or 0),
        last_backup_at=guest.last_backup_at,
        schedule_cron=guest.schedule_cron,
        schedule_enabled=guest.schedule_enabled,
        last_tested_at=guest.last_tested_at,
        next_due_at=guest.next_due_at,
        latest_run=_latest_run_out(latest_run),
    )


def _validate_restorable(db: Session, guest: Guest, *, force: bool) -> None:
    """
    Reject a restore request that cannot succeed.

    Confirms against live Proxmox state that the guest still exists, is covered
    by a Datacenter backup job, and has at least one PBS snapshot. ``force``
    skips the checks for deliberate admin overrides.
    """
    if force:
        return
    host = db.query(ProxmoxHost).filter_by(id=guest.host_id).first()
    if not host:
        raise HTTPException(status_code=400, detail="Host not found for this guest")

    result = preflight_restore_check(db, guest, host)
    if result.ok:
        return
    if result.guest_missing:
        raise HTTPException(status_code=404, detail=result.reason)
    raise HTTPException(
        status_code=400,
        detail=f"{result.reason} Pass force=true to run anyway.",
    )


@router.get("", response_model=list[GuestOut])
def list_guests(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list:
    hosts = {h.id: h.name for h in db.query(ProxmoxHost).all()}
    guests = db.query(Guest).order_by(Guest.vmid).all()
    latest = _latest_runs_by_guest(db)
    return [_guest_out(g, hosts.get(g.host_id, ""), latest.get(g.id)) for g in guests]


@router.patch("/{guest_id}", response_model=GuestOut)
def update_guest(
    guest_id: int,
    body: GuestUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> GuestOut:
    guest = db.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "schedule_cron" and value == "":
            value = None
        setattr(guest, key, value)
    settings = get_app_settings(db)
    guest.next_due_at = compute_next_due(guest, settings.global_cron)
    db.commit()
    host = db.query(ProxmoxHost).filter_by(id=guest.host_id).first()
    latest = (
        db.query(RestoreRun)
        .filter(RestoreRun.guest_id == guest.id)
        .order_by(RestoreRun.id.desc())
        .first()
    )
    return _guest_out(guest, host.name if host else "", latest)


@router.post("/{guest_id}/run", response_model=RunOut)
def run_now(
    guest_id: int,
    force: bool = Query(False, description="Skip pre-flight backup/existence validation"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RunOut:
    guest = db.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    _validate_restorable(db, guest, force=force)
    # Prevent duplicate queued/running for same guest
    active = (
        db.query(RestoreRun)
        .filter(
            RestoreRun.guest_id == guest.id,
            RestoreRun.status.in_(("queued", "running")),
        )
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="A run is already queued or running for this guest")

    run = RestoreRun(
        guest_id=guest.id,
        host_id=guest.host_id,
        source_vmid=guest.vmid,
        source_name=guest.name,
        guest_type=guest.guest_type,
        status="queued",
        trigger="manual",
        progress_pct=0.0,
        progress_label="Queued",
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunOut.model_validate(run)


@router.post("/refresh-schedule")
def refresh_schedule(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    refresh_guest_due_times(db)
    return {"ok": True}
