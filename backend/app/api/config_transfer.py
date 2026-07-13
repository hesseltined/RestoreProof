"""
Purpose: Configuration export/import API for VM rebuild and migration.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.0.1
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import User
from app.services.config_transfer import export_config_json, import_config_bundle, parse_import_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


class ConfigImportRequest(BaseModel):
    bundle: dict
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    import_users: bool = False


class ConfigImportSummary(BaseModel):
    mode: str
    hosts_created: int
    hosts_updated: int
    guest_overrides_applied: int
    guest_overrides_pending: int
    users_created: int
    users_skipped: int


@router.get("/export")
def export_config(
    include_users: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Return configuration bundle as JSON (client triggers download)."""
    payload = export_config_json(db, include_users=include_users)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return {
        "filename": f"restoreproof-config-{stamp}.json",
        "content_type": "application/json",
        "data": payload,
    }


def _run_import(
    db: Session,
    bundle: dict,
    *,
    mode: str,
    import_users: bool,
) -> ConfigImportSummary:
    try:
        summary = import_config_bundle(
            db,
            bundle,
            mode=mode,  # type: ignore[arg-type]
            import_users=import_users,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Config import database error")
        raise HTTPException(
            status_code=400,
            detail=f"Import failed (database): {exc.__class__.__name__}",
        ) from exc
    except OSError as exc:
        db.rollback()
        logger.exception("Config import filesystem error")
        raise HTTPException(
            status_code=400,
            detail=f"Import failed writing SSH keys: {exc}",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Config import unexpected error")
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {exc.__class__.__name__}: {exc}",
        ) from exc
    return ConfigImportSummary(**summary)


@router.post("/import", response_model=ConfigImportSummary)
def import_config(
    body: ConfigImportRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ConfigImportSummary:
    return _run_import(
        db, body.bundle, mode=body.mode, import_users=body.import_users
    )


@router.post("/import/file", response_model=ConfigImportSummary)
async def import_config_file(
    file: UploadFile = File(...),
    mode: str = Query(default="merge", pattern="^(merge|replace)$"),
    import_users: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ConfigImportSummary:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        bundle = parse_import_file(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_import(db, bundle, mode=mode, import_users=import_users)
