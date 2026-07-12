"""
Purpose: Guest inventory, exclude/schedule overrides, run-now.
Author: Doug Hesseltine
Created: 2026-07-12
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Guest, ProxmoxHost, RestoreRun, User
from app.schemas import GuestOut, GuestUpdate, RunOut
from app.services.bootstrap import get_app_settings
from app.services.scheduler import compute_next_due, refresh_guest_due_times

router = APIRouter(prefix="/guests", tags=["guests"])


def _guest_out(guest: Guest, host_name: str = "") -> GuestOut:
    return GuestOut(
        id=guest.id,
        host_id=guest.host_id,
        host_name=host_name,
        vmid=guest.vmid,
        name=guest.name,
        guest_type=guest.guest_type,
        node=guest.node,
        status=guest.status,
        excluded=guest.excluded,
        schedule_cron=guest.schedule_cron,
        schedule_enabled=guest.schedule_enabled,
        last_tested_at=guest.last_tested_at,
        next_due_at=guest.next_due_at,
    )


@router.get("", response_model=list[GuestOut])
def list_guests(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list:
    hosts = {h.id: h.name for h in db.query(ProxmoxHost).all()}
    guests = db.query(Guest).order_by(Guest.vmid).all()
    return [_guest_out(g, hosts.get(g.host_id, "")) for g in guests]


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
    return _guest_out(guest, host.name if host else "")


@router.post("/{guest_id}/run", response_model=RunOut)
def run_now(
    guest_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> RunOut:
    guest = db.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
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
