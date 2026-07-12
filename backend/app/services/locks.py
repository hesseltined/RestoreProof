"""
Purpose: Global single-flight lock for restore tests.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.1.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import JobLock


def get_lock(db: Session) -> JobLock:
    lock = db.query(JobLock).filter_by(lock_name="global_restore").first()
    if not lock:
        lock = JobLock(lock_name="global_restore")
        db.add(lock)
        db.commit()
        db.refresh(lock)
    return lock


def try_acquire(db: Session, holder: str, run_id: int) -> bool:
    lock = get_lock(db)
    if lock.held_by:
        return False
    lock.held_by = holder
    lock.held_since = datetime.now(timezone.utc)
    lock.run_id = run_id
    db.commit()
    return True


def release(db: Session, holder: Optional[str] = None) -> None:
    lock = get_lock(db)
    if holder and lock.held_by and lock.held_by != holder:
        return
    lock.held_by = None
    lock.held_since = None
    lock.run_id = None
    db.commit()


def force_release(db: Session) -> Optional[int]:
    """Clear the global lock regardless of holder. Returns previous run_id if any."""
    lock = get_lock(db)
    prev = lock.run_id
    lock.held_by = None
    lock.held_since = None
    lock.run_id = None
    db.commit()
    return prev
