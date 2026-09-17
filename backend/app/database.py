"""
Purpose: SQLAlchemy engine and session helpers.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-17
Version: 1.10.0
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Add columns introduced after initial create_all (Postgres IF NOT EXISTS)."""
    statements = [
        "ALTER TABLE proxmox_hosts ADD COLUMN IF NOT EXISTS api_ok_at TIMESTAMPTZ",
        "ALTER TABLE proxmox_hosts ADD COLUMN IF NOT EXISTS ssh_ok_at TIMESTAMPTZ",
        "ALTER TABLE smtp_settings ADD COLUMN IF NOT EXISTS smtp_ok_at TIMESTAMPTZ",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS schedule_batch_size INTEGER DEFAULT 1",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS schedule_coverage_goal VARCHAR(32) DEFAULT 'monthly'",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS progress_pct DOUBLE PRECISION",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS progress_label VARCHAR(120)",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS proxmox_upid VARCHAR(255)",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS proxmox_node VARCHAR(120)",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS cpu_cores INTEGER",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS memory_bytes BIGINT",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS disk_bytes BIGINT",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS backup_count INTEGER",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS backup_used_index INTEGER",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS latest_backup_volid VARCHAR(512) DEFAULT ''",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS used_fallback_backup BOOLEAN DEFAULT FALSE",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS backups_attempted INTEGER DEFAULT 0",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS result_summary TEXT DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS setup_wizard_completed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS in_backup_job BOOLEAN DEFAULT TRUE",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS backup_job_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS backup_job_summary VARCHAR(512) DEFAULT ''",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS backup_snapshot_count INTEGER DEFAULT 0",
        "ALTER TABLE guests ADD COLUMN IF NOT EXISTS last_backup_at TIMESTAMPTZ",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS gap_alert_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS gap_alert_hours INTEGER DEFAULT 26",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS gap_alert_last_sent_at TIMESTAMPTZ",
        "ALTER TABLE restore_runs ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS notified_at_backfilled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS public_base_url VARCHAR(512) DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_check_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_dismissed_version VARCHAR(64) DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_last_checked_at TIMESTAMPTZ",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_latest_version VARCHAR(64) DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_latest_url VARCHAR(512) DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_latest_notes TEXT DEFAULT ''",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS update_latest_source VARCHAR(32) DEFAULT ''",
        # One-shot: mark pre-digest runs as already mailed so the first worker
        # loop after upgrade does not dump history into a single digest.
        """
        UPDATE restore_runs AS r
        SET notified_at = COALESCE(r.finished_at, r.created_at)
        FROM app_settings AS s
        WHERE r.notified_at IS NULL
          AND r.status NOT IN ('queued', 'running')
          AND COALESCE(s.notified_at_backfilled, FALSE) = FALSE
        """,
        "UPDATE app_settings SET notified_at_backfilled = TRUE",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
