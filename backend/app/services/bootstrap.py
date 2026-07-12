"""
Purpose: Ensure singleton settings rows exist.
Author: Doug Hesseltine
Created: 2026-07-12
Version: 1.0.0
"""

from sqlalchemy.orm import Session

from app.models import AppSettings, JobLock, SmtpSettings


def ensure_defaults(db: Session) -> None:
    if not db.query(AppSettings).first():
        db.add(AppSettings())
    if not db.query(SmtpSettings).first():
        db.add(SmtpSettings())
    if not db.query(JobLock).filter_by(lock_name="global_restore").first():
        db.add(JobLock(lock_name="global_restore"))
    db.commit()


def get_app_settings(db: Session) -> AppSettings:
    ensure_defaults(db)
    return db.query(AppSettings).first()  # type: ignore[return-value]


def get_smtp_settings(db: Session) -> SmtpSettings:
    ensure_defaults(db)
    return db.query(SmtpSettings).first()  # type: ignore[return-value]
