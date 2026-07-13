"""
Purpose: SQLAlchemy engine and session helpers.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.5.0
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
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
