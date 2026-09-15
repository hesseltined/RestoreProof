"""
Purpose: Ensure singleton settings rows exist.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-31
Version: 1.3.0
"""

from sqlalchemy.orm import Session

from app.models import AppSettings, HeartbeatSettings, JobLock, PushSettings, SmtpSettings
from app.services.email_templates import (
    DEFAULT_FAILURE_BODY,
    DEFAULT_FAILURE_SUBJECT,
    DEFAULT_SUCCESS_BODY,
    DEFAULT_SUCCESS_SUBJECT,
    is_legacy_template,
)


def ensure_defaults(db: Session) -> None:
    if not db.query(AppSettings).first():
        db.add(
            AppSettings(
                email_success_subject=DEFAULT_SUCCESS_SUBJECT,
                email_failure_subject=DEFAULT_FAILURE_SUBJECT,
                email_success_body=DEFAULT_SUCCESS_BODY,
                email_failure_body=DEFAULT_FAILURE_BODY,
            )
        )
        db.commit()
    settings = db.query(AppSettings).first()
    if settings and is_legacy_template(settings):
        settings.email_success_subject = DEFAULT_SUCCESS_SUBJECT
        settings.email_failure_subject = DEFAULT_FAILURE_SUBJECT
        settings.email_success_body = DEFAULT_SUCCESS_BODY
        settings.email_failure_body = DEFAULT_FAILURE_BODY
    if not db.query(SmtpSettings).first():
        db.add(SmtpSettings())
    if not db.query(PushSettings).first():
        db.add(PushSettings())
    if not db.query(HeartbeatSettings).first():
        db.add(HeartbeatSettings())
    if not db.query(JobLock).filter_by(lock_name="global_restore").first():
        db.add(JobLock(lock_name="global_restore"))
    db.commit()


def get_app_settings(db: Session) -> AppSettings:
    ensure_defaults(db)
    return db.query(AppSettings).first()  # type: ignore[return-value]


def get_smtp_settings(db: Session) -> SmtpSettings:
    ensure_defaults(db)
    return db.query(SmtpSettings).first()  # type: ignore[return-value]


def get_push_settings(db: Session) -> PushSettings:
    ensure_defaults(db)
    return db.query(PushSettings).first()  # type: ignore[return-value]


def get_heartbeat_settings(db: Session) -> HeartbeatSettings:
    ensure_defaults(db)
    return db.query(HeartbeatSettings).first()  # type: ignore[return-value]
