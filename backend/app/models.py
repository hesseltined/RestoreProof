"""
Purpose: SQLAlchemy ORM models for RestoreProof.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-17
Version: 1.11.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branding_title: Mapped[str] = mapped_column(String(120), default="RestoreProof")
    boot_wait_seconds: Mapped[int] = mapped_column(Integer, default=60)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    retention_max_runs: Mapped[int] = mapped_column(Integer, default=200)
    global_cron: Mapped[str] = mapped_column(String(120), default="0 2 * * *")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # How many restore tests to enqueue per schedule tick (nightly batch, etc.)
    schedule_batch_size: Mapped[int] = mapped_column(Integer, default=1)
    # Planning helper: weekly | monthly | custom
    schedule_coverage_goal: Mapped[str] = mapped_column(String(32), default="monthly")
    enforce_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Guided setup checklist dismissed/completed (separate from first-admin setup_completed)
    setup_wizard_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_on_success: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_to: Mapped[str] = mapped_column(Text, default="")
    notify_cc: Mapped[str] = mapped_column(Text, default="")
    # Public origin for email/push links. Empty = APP_BASE_URL env (localhost default).
    public_base_url: Mapped[str] = mapped_column(String(512), default="")
    update_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    update_dismissed_version: Mapped[str] = mapped_column(String(64), default="")
    update_last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    update_latest_version: Mapped[str] = mapped_column(String(64), default="")
    update_latest_url: Mapped[str] = mapped_column(String(512), default="")
    update_latest_notes: Mapped[str] = mapped_column(Text, default="")
    update_latest_source: Mapped[str] = mapped_column(String(32), default="")
    # Email/push when the schedule is on but no restore finishes for N hours.
    gap_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    gap_alert_hours: Mapped[int] = mapped_column(Integer, default=26)
    gap_alert_last_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # One-shot flag for the notified_at backfill in ensure_schema. Not an API field.
    notified_at_backfilled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_success_subject: Mapped[str] = mapped_column(
        String(255), default="✅ RestoreProof passed — {{guest_name}} (VMID {{vmid}})"
    )
    email_failure_subject: Mapped[str] = mapped_column(
        String(255), default="❌ RestoreProof failed — {{guest_name}} (VMID {{vmid}})"
    )
    email_success_body: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    email_failure_body: Mapped[str] = mapped_column(
        Text,
        default="",
    )


class SmtpSettings(Base):
    __tablename__ = "smtp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="generic")
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    username: Mapped[str] = mapped_column(String(255), default="")
    password_enc: Mapped[str] = mapped_column(Text, default="")
    from_email: Mapped[str] = mapped_column(String(255), default="")
    from_name: Mapped[str] = mapped_column(String(120), default="RestoreProof")
    smtp_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSettings(Base):
    """
    Push notification delivery (ntfy). Separate from SMTP so either channel can
    be configured, tested, and disabled on its own.
    """

    __tablename__ = "push_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(64), default="ntfy")
    # Full topic URL, e.g. https://ntfy.sh/restoreproof-4f2b9c
    url: Mapped[str] = mapped_column(String(512), default="")
    # Optional access token for protected/self-hosted topics
    token_enc: Mapped[str] = mapped_column(Text, default="")
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    on_success: Mapped[bool] = mapped_column(Boolean, default=False)
    on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    push_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class HeartbeatSettings(Base):
    """
    Dead-man's-switch ping. The worker calls ``url`` after each healthy loop;
    an external monitor (Uptime Kuma push, Healthchecks.io, Cronitor) raises the
    alarm when the pings stop — which is the only way to catch a dead worker,
    since a silent worker looks identical to "no failures".
    """

    __tablename__ = "heartbeat_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(512), default="")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ping_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="")


class ProxmoxHost(Base):
    __tablename__ = "proxmox_hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    api_url: Mapped[str] = mapped_column(String(512))
    # root@pam!tokenid
    token_id: Mapped[str] = mapped_column(String(255), default="")
    token_secret_enc: Mapped[str] = mapped_column(Text, default="")
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    ssh_host: Mapped[str] = mapped_column(String(255), default="")
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), default="root")
    ssh_private_key_path: Mapped[str] = mapped_column(String(512), default="")
    preferred_restore_storage: Mapped[str] = mapped_column(String(120), default="")
    test_vmid_start: Mapped[int] = mapped_column(Integer, default=9000)
    test_vmid_end: Mapped[int] = mapped_column(Integer, default=9099)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    api_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ssh_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    guests: Mapped[list[Guest]] = relationship(back_populates="host", cascade="all, delete-orphan")


class Guest(Base):
    __tablename__ = "guests"
    __table_args__ = (UniqueConstraint("host_id", "vmid", name="uq_host_vmid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("proxmox_hosts.id", ondelete="CASCADE"))
    vmid: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    guest_type: Mapped[str] = mapped_column(String(16))  # qemu | lxc
    node: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(64), default="")
    # Specs from Proxmox cluster/resources (refreshed on host sync)
    cpu_cores: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # maxmem
    disk_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # maxdisk
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    # True when VMID appears in a Proxmox vzdump/backup job (refreshed on host sync)
    in_backup_job: Mapped[bool] = mapped_column(Boolean, default=True)
    # At least one covering job is currently enabled
    backup_job_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Comma-separated job ids / schedules for UI (e.g. "backup-abc (sun 01:00)")
    backup_job_summary: Mapped[str] = mapped_column(String(512), default="")
    # PBS snapshot inventory seen at last host sync
    backup_snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    last_backup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    schedule_cron: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    host: Mapped[ProxmoxHost] = relationship(back_populates="guests")
    runs: Mapped[list[RestoreRun]] = relationship(back_populates="guest")


class JobLock(Base):
    __tablename__ = "job_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lock_name: Mapped[str] = mapped_column(String(64), unique=True, default="global_restore")
    held_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    held_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class RestoreRun(Base):
    __tablename__ = "restore_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guest_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("guests.id", ondelete="SET NULL"), nullable=True
    )
    host_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("proxmox_hosts.id", ondelete="SET NULL"), nullable=True
    )
    source_vmid: Mapped[int] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(255), default="")
    guest_type: Mapped[str] = mapped_column(String(16), default="qemu")
    test_vmid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backup_volid: Mapped[str] = mapped_column(String(512), default="")
    # Inventory / fallback metadata (set during restore)
    backup_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backup_used_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-based
    latest_backup_volid: Mapped[str] = mapped_column(String(512), default="")
    used_fallback_backup: Mapped[bool] = mapped_column(Boolean, default=False)
    backups_attempted: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    # queued | running | success | failed
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual | schedule
    # Live restore progress (updated while status == running)
    progress_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    progress_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    proxmox_upid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    proxmox_node: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String(32), default="none")
    # screenshot | container_proof | none
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when email/push for this run was sent or skipped. Null = still waiting
    # to be included in tonight's scheduled digest.
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    guest: Mapped[Optional[Guest]] = relationship(back_populates="runs")
