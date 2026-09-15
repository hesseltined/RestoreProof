"""
Purpose: Restore run history, evidence download, resend email, retry, pagination.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-31
Version: 1.4.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.guests import _validate_restorable
from app.database import get_db
from app.deps import get_current_user
from app.models import Guest, RestoreRun, User
from app.schemas import RunDetail, RunOut, RunPageOut
from app.services.remediation import remediation_for_runs, run_out_with_remediation
from app.services.restore import notify_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunPageOut)
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RunPageOut:
    total = db.query(RestoreRun).count()
    rows = (
        db.query(RestoreRun)
        .order_by(RestoreRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    remediated_by = remediation_for_runs(db, rows)
    return RunPageOut(
        items=[run_out_with_remediation(r, remediated_by) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> RunDetail:
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetail.model_validate(run)


@router.get("/{run_id}/evidence")
def get_evidence(
    run_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run or not run.evidence_path:
        raise HTTPException(status_code=404, detail="Evidence not found")
    path = Path(run.evidence_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Evidence file missing")
    media = "image/png" if path.suffix.lower() == ".png" else "application/json"
    return FileResponse(path, media_type=media, filename=path.name)


@router.post("/{run_id}/resend-email")
async def resend_email(
    run_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("success", "failed"):
        raise HTTPException(status_code=400, detail="Run is not finished")
    await notify_run(db, run)
    return {"ok": True}


@router.post("/{run_id}/retry", response_model=RunOut)
def retry_run(
    run_id: int,
    force: bool = Query(False, description="Skip pre-flight backup/existence validation"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RunOut:
    """Queue a new restore drill for the same guest after a failed run."""
    run = db.query(RestoreRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed runs can be retried")
    if not run.guest_id:
        raise HTTPException(
            status_code=400,
            detail="Guest is no longer in inventory — sync hosts and run from Guests",
        )
    guest = db.query(Guest).filter_by(id=run.guest_id).first()
    if not guest:
        raise HTTPException(status_code=400, detail="Guest not found")
    _validate_restorable(db, guest, force=force)

    active = (
        db.query(RestoreRun)
        .filter(
            RestoreRun.guest_id == guest.id,
            RestoreRun.status.in_(("queued", "running")),
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"A run is already {active.status} for this guest (#{active.id})",
        )

    new_run = RestoreRun(
        guest_id=guest.id,
        host_id=guest.host_id,
        source_vmid=guest.vmid,
        source_name=guest.name,
        guest_type=guest.guest_type,
        status="queued",
        trigger="retry",
        progress_pct=0.0,
        progress_label="Queued (retry)",
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    return RunOut.model_validate(new_run)
