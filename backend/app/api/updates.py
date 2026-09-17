"""
Purpose: GitHub / Docker Hub version-check endpoints for in-app upgrades.
Author: Doug Hesseltine
Created: 2026-09-17
Modified: 2026-09-17
Version: 1.0.0
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.bootstrap import get_app_settings
from app.services.updates import get_update_status

router = APIRouter(tags=["updates"])


class DismissBody(BaseModel):
    version: str = ""


class UpdateCheckBody(BaseModel):
    enabled: bool


@router.get("/updates")
def read_updates(
    refresh: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    settings = get_app_settings(db)
    return get_update_status(db, settings, refresh=refresh)


@router.post("/updates/check")
def check_updates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    settings = get_app_settings(db)
    return get_update_status(db, settings, refresh=True)


@router.post("/updates/dismiss")
def dismiss_update(
    body: DismissBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    settings = get_app_settings(db)
    version = (body.version or settings.update_latest_version or "").strip()
    settings.update_dismissed_version = version
    db.commit()
    return get_update_status(db, settings, refresh=False)


@router.put("/updates/preference")
def set_update_preference(
    body: UpdateCheckBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    settings = get_app_settings(db)
    settings.update_check_enabled = body.enabled
    db.commit()
    return get_update_status(db, settings, refresh=False)
