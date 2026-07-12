"""
Purpose: Restore run history, evidence download, resend email.
Author: Doug Hesseltine
Created: 2026-07-12
Version: 1.0.0
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import RestoreRun, User
from app.schemas import RunDetail, RunOut
from app.services.restore import notify_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def list_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    rows = (
        db.query(RestoreRun)
        .order_by(RestoreRun.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [RunOut.model_validate(r) for r in rows]


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
