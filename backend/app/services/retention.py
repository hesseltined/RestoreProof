"""
Purpose: Retention cleanup for old restore runs and evidence files.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-30
Version: 1.2.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Guest, RestoreRun
from app.services.bootstrap import get_app_settings

logger = logging.getLogger(__name__)


def apply_retention(db: Session) -> int:
    settings = get_app_settings(db)
    deleted = 0

    # Keep latest successful/failed run per guest always
    keep_ids: set[int] = set()
    guests = db.query(Guest).all()
    for g in guests:
        latest = (
            db.query(RestoreRun)
            .filter(RestoreRun.guest_id == g.id)
            .order_by(RestoreRun.created_at.desc())
            .first()
        )
        if latest:
            keep_ids.add(latest.id)

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    old_runs = (
        db.query(RestoreRun)
        .filter(RestoreRun.created_at < cutoff)
        .order_by(RestoreRun.created_at.asc())
        .all()
    )
    for run in old_runs:
        if run.id in keep_ids:
            continue
        _delete_run_files(run)
        db.delete(run)
        deleted += 1

    # Cap max runs globally
    total = db.query(RestoreRun).count()
    if total > settings.retention_max_runs:
        overflow = total - settings.retention_max_runs
        candidates = (
            db.query(RestoreRun)
            .order_by(RestoreRun.created_at.asc())
            .limit(overflow * 2)
            .all()
        )
        removed = 0
        for run in candidates:
            if removed >= overflow:
                break
            if run.id in keep_ids:
                continue
            _delete_run_files(run)
            db.delete(run)
            deleted += 1
            removed += 1

    db.commit()
    return deleted


def _delete_run_files(run: RestoreRun) -> None:
    if run.evidence_path:
        try:
            Path(run.evidence_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete evidence %s", run.evidence_path)


def purge_runs_before(db: Session, before: datetime) -> int:
    """
    Delete all restore runs created strictly before ``before`` (UTC),
    including evidence files. Intended for explicit admin purge.
    """
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    else:
        before = before.astimezone(timezone.utc)

    rows = (
        db.query(RestoreRun)
        .filter(RestoreRun.created_at < before)
        .order_by(RestoreRun.created_at.asc())
        .all()
    )
    deleted = 0
    for run in rows:
        _delete_run_files(run)
        db.delete(run)
        deleted += 1
    db.commit()
    return deleted


def purge_stale_runs(
    db: Session,
    *,
    orphaned: bool = True,
    not_backed_up: bool = True,
) -> tuple[int, int, int]:
    """
    Delete restore runs for guests that are gone or not configured for backups.

    Returns (total_deleted, orphaned_deleted, not_backed_up_deleted).
    """
    orphaned_deleted = 0
    not_backed_up_deleted = 0
    seen_ids: set[int] = set()

    if orphaned:
        rows = (
            db.query(RestoreRun)
            .filter(RestoreRun.guest_id.is_(None))
            .order_by(RestoreRun.created_at.asc())
            .all()
        )
        for run in rows:
            if run.id in seen_ids:
                continue
            _delete_run_files(run)
            db.delete(run)
            seen_ids.add(run.id)
            orphaned_deleted += 1

    if not_backed_up:
        guest_ids = [
            g.id
            for g in db.query(Guest).filter(Guest.in_backup_job.is_(False)).all()
        ]
        if guest_ids:
            rows = (
                db.query(RestoreRun)
                .filter(RestoreRun.guest_id.in_(guest_ids))
                .order_by(RestoreRun.created_at.asc())
                .all()
            )
            for run in rows:
                if run.id in seen_ids:
                    continue
                _delete_run_files(run)
                db.delete(run)
                seen_ids.add(run.id)
                not_backed_up_deleted += 1

    db.commit()
    return orphaned_deleted + not_backed_up_deleted, orphaned_deleted, not_backed_up_deleted
