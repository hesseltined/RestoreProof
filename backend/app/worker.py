"""
Purpose: Background worker — process queued restores, schedule rotation, retention.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.3.0
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.database import Base, SessionLocal, engine, ensure_schema
from app.models import RestoreRun
from app.services.bootstrap import ensure_defaults, get_app_settings
from app.services.restore import execute_restore_run, recover_orphaned_runs
from app.services.retention import apply_retention
from app.services.scheduler import pick_next_guest, refresh_guest_due_times

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("restoreproof.worker")


def process_queue_once() -> bool:
    """Process one queued run if present. Returns True if work was done."""
    db = SessionLocal()
    try:
        run = (
            db.query(RestoreRun)
            .filter(RestoreRun.status == "queued")
            .order_by(RestoreRun.created_at.asc())
            .first()
        )
        if not run:
            return False
        run_id = run.id
        logger.info("Processing restore run %s", run_id)
    finally:
        db.close()

    db = SessionLocal()
    try:
        execute_restore_run(db, run_id)
    finally:
        db.close()
    return True


def maybe_enqueue_scheduled() -> None:
    db = SessionLocal()
    try:
        settings = get_app_settings(db)
        if not settings.schedule_enabled:
            return
        # Don't enqueue if something is queued/running (one restore at a time)
        busy = (
            db.query(RestoreRun)
            .filter(RestoreRun.status.in_(("queued", "running")))
            .first()
        )
        if busy:
            return
        guest = pick_next_guest(db)
        if not guest:
            return
        run = RestoreRun(
            guest_id=guest.id,
            host_id=guest.host_id,
            source_vmid=guest.vmid,
            source_name=guest.name,
            guest_type=guest.guest_type,
            status="queued",
            trigger="schedule",
            progress_pct=0.0,
            progress_label="Queued",
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)
        from app.services.scheduler import compute_next_due

        guest.next_due_at = compute_next_due(
            guest, settings.global_cron, datetime.now(timezone.utc)
        )
        db.commit()
        batch = max(1, int(getattr(settings, "schedule_batch_size", 1) or 1))
        logger.info(
            "Enqueued scheduled test for guest %s (VMID %s) [batch size %s]",
            guest.name,
            guest.vmid,
            batch,
        )
    finally:
        db.close()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        ensure_defaults(db)
        refresh_guest_due_times(db)
        recovered = recover_orphaned_runs(db)
        if recovered:
            logger.warning("Startup recovery closed %s interrupted run(s)", recovered)
    finally:
        db.close()

    logger.info("RestoreProof worker started")
    loop = 0
    while True:
        try:
            worked = process_queue_once()
            if not worked:
                maybe_enqueue_scheduled()
            loop += 1
            if loop % 60 == 0:
                db = SessionLocal()
                try:
                    deleted = apply_retention(db)
                    if deleted:
                        logger.info("Retention deleted %s runs", deleted)
                finally:
                    db.close()
        except Exception:  # noqa: BLE001
            logger.exception("Worker loop error")
        time.sleep(5)


if __name__ == "__main__":
    main()
