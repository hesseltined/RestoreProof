"""
Purpose: Pydantic request/response schemas.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-31
Version: 1.11.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    requires_2fa: bool = False
    setup_required: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class SetupAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    is_admin: bool
    totp_enabled: bool

    model_config = {"from_attributes": True}


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpEnableRequest(BaseModel):
    code: str


class AppSettingsOut(BaseModel):
    branding_title: str
    boot_wait_seconds: int
    retention_days: int
    retention_max_runs: int
    global_cron: str
    schedule_enabled: bool
    schedule_batch_size: int = 1
    schedule_coverage_goal: str = "monthly"
    enforce_2fa: bool
    setup_completed: bool
    notify_on_success: bool
    notify_on_failure: bool
    notify_to: str
    notify_cc: str
    email_success_subject: str
    email_failure_subject: str
    email_success_body: str
    email_failure_body: str

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    branding_title: Optional[str] = None
    boot_wait_seconds: Optional[int] = None
    retention_days: Optional[int] = None
    retention_max_runs: Optional[int] = None
    global_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    schedule_batch_size: Optional[int] = Field(default=None, ge=1, le=500)
    schedule_coverage_goal: Optional[str] = None
    enforce_2fa: Optional[bool] = None
    notify_on_success: Optional[bool] = None
    notify_on_failure: Optional[bool] = None
    notify_to: Optional[str] = None
    notify_cc: Optional[str] = None
    email_success_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None
    email_success_body: Optional[str] = None
    email_failure_body: Optional[str] = None


class PurgeRunsRequest(BaseModel):
    """Delete restore runs created strictly before this UTC datetime (ISO)."""

    before: datetime


class PurgeRunsOut(BaseModel):
    deleted: int
    before: datetime


class PurgeStaleRunsRequest(BaseModel):
    """
    Delete restore runs that no longer map to a testable guest.

    - orphaned: guest was removed from Proxmox (guest_id is NULL)
    - not_backed_up: guest exists but is not in any Proxmox backup job
    """

    orphaned: bool = True
    not_backed_up: bool = True


class PurgeStaleRunsOut(BaseModel):
    deleted: int
    orphaned_deleted: int = 0
    not_backed_up_deleted: int = 0


class SchedulePlanOut(BaseModel):
    """Planning numbers for coverage / batch sizing (excludes excluded guests)."""

    total_guests: int
    excluded_count: int
    not_backed_up_count: int = 0
    no_snapshot_count: int = 0
    eligible_count: int
    schedule_batch_size: int
    schedule_coverage_goal: str
    global_cron: str
    ticks_per_week: float
    ticks_per_month: float
    suggested_batch_weekly: int
    suggested_batch_monthly: int
    ticks_to_cover_all: int
    days_to_cover_all_estimate: float
    cover_weekly_ok: bool
    cover_monthly_ok: bool
    enqueued_this_window: int
    window_remaining: int
    summary: str


class SmtpOut(BaseModel):
    provider: str
    host: str
    port: int
    use_tls: bool
    use_ssl: bool
    username: str
    from_email: str
    from_name: str
    password_set: bool
    smtp_ok_at: Optional[datetime] = None


class SmtpUpdate(BaseModel):
    provider: str = "generic"
    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    username: str = ""
    password: Optional[str] = None
    from_email: str = ""
    from_name: str = "RestoreProof"


class SmtpTestRequest(BaseModel):
    to_email: EmailStr


class PushOut(BaseModel):
    enabled: bool
    provider: str
    url: str
    verify_ssl: bool
    on_success: bool
    on_failure: bool
    token_set: bool
    push_ok_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PushUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    url: Optional[str] = None
    verify_ssl: Optional[bool] = None
    on_success: Optional[bool] = None
    on_failure: Optional[bool] = None
    # Blank/omitted keeps the stored token; "-" clears it.
    token: Optional[str] = None


class HeartbeatOut(BaseModel):
    enabled: bool
    url: str
    interval_seconds: int
    verify_ssl: bool
    last_ping_at: Optional[datetime] = None
    last_error: str = ""

    model_config = {"from_attributes": True}


class HeartbeatUpdate(BaseModel):
    enabled: Optional[bool] = None
    url: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=30, le=86400)
    verify_ssl: Optional[bool] = None


class HostCreate(BaseModel):
    name: str
    api_url: str
    token_id: str
    token_secret: str
    verify_ssl: bool = False
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = "root"
    preferred_restore_storage: str = ""
    test_vmid_start: int = 9000
    test_vmid_end: int = 9099
    enabled: bool = True


class HostUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    token_id: Optional[str] = None
    token_secret: Optional[str] = None
    verify_ssl: Optional[bool] = None
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_user: Optional[str] = None
    preferred_restore_storage: Optional[str] = None
    test_vmid_start: Optional[int] = None
    test_vmid_end: Optional[int] = None
    enabled: Optional[bool] = None


class HostLatestRunOut(BaseModel):
    id: int
    status: str
    source_name: str
    source_vmid: int
    guest_type: str
    evidence_kind: str
    error_message: Optional[str] = None
    result_summary: Optional[str] = None
    used_fallback_backup: bool = False
    backup_count: Optional[int] = None
    backup_used_index: Optional[int] = None
    finished_at: Optional[datetime] = None
    started_at: Optional[datetime] = None


class HostOut(BaseModel):
    id: int
    name: str
    api_url: str
    token_id: str
    verify_ssl: bool
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_private_key_path: str
    preferred_restore_storage: str
    test_vmid_start: int
    test_vmid_end: int
    enabled: bool
    last_sync_at: Optional[datetime]
    api_ok_at: Optional[datetime] = None
    ssh_ok_at: Optional[datetime] = None
    last_error: Optional[str]
    has_token_secret: bool
    has_ssh_key: bool
    latest_run: Optional[HostLatestRunOut] = None

    model_config = {"from_attributes": True}


class GuestLatestRunOut(BaseModel):
    """Compact last restore attempt for the Guests inventory row."""

    id: int
    status: str
    used_fallback_backup: bool = False
    finished_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    error_message: Optional[str] = None


class GuestOut(BaseModel):
    id: int
    host_id: int
    host_name: str = ""
    vmid: int
    name: str
    guest_type: str
    node: str
    status: str
    cpu_cores: Optional[int] = None
    memory_bytes: Optional[int] = None
    disk_bytes: Optional[int] = None
    excluded: bool
    in_backup_job: bool = True
    backup_job_enabled: bool = False
    backup_job_summary: str = ""
    backup_snapshot_count: int = 0
    last_backup_at: Optional[datetime] = None
    schedule_cron: Optional[str]
    schedule_enabled: bool
    last_tested_at: Optional[datetime]
    next_due_at: Optional[datetime]
    latest_run: Optional[GuestLatestRunOut] = None

    model_config = {"from_attributes": True}


class GuestUpdate(BaseModel):
    excluded: Optional[bool] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None


class RunOut(BaseModel):
    id: int
    guest_id: Optional[int]
    host_id: Optional[int]
    source_vmid: int
    source_name: str
    guest_type: str
    test_vmid: Optional[int]
    backup_volid: str
    backup_count: Optional[int] = None
    backup_used_index: Optional[int] = None
    latest_backup_volid: str = ""
    used_fallback_backup: bool = False
    backups_attempted: int = 0
    result_summary: str = ""
    status: str
    trigger: str
    progress_pct: Optional[float] = None
    progress_label: Optional[str] = None
    proxmox_upid: Optional[str] = None
    proxmox_node: Optional[str] = None
    error_message: Optional[str]
    evidence_path: Optional[str]
    evidence_kind: str
    evidence_json: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    # Dashboard enrichment: failed run (≤7 days) later succeeded for same guest
    remediated: bool = False
    remediated_by_run_id: Optional[int] = None

    model_config = {"from_attributes": True}


class RunDetail(RunOut):
    log_text: str


class RunPageOut(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int


class ActiveRunOut(BaseModel):
    id: int
    status: str
    source_name: str
    source_vmid: int
    guest_type: str
    host_id: Optional[int] = None
    test_vmid: Optional[int] = None
    progress_pct: Optional[float] = None
    progress_label: Optional[str] = None
    started_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DashboardOut(BaseModel):
    setup_completed: bool
    schedule_enabled: bool
    global_cron: str
    lock_held: bool
    lock_held_by: Optional[str]
    lock_run_id: Optional[int]
    recent_runs: list[RunOut]
    # Total runs on record, so the UI can say "showing 10 of 143".
    recent_runs_total: int = 0
    guest_count: int
    excluded_count: int
    host_count: int
    next_due: Optional[GuestOut]
    active_run: Optional[ActiveRunOut] = None


class StatusOut(BaseModel):
    app: str = "RestoreProof"
    version: str = "1.0.0"
    setup_completed: bool
    user_count: int


class SetupStepOut(BaseModel):
    id: str
    title: str
    body: str
    to: str
    done: bool
    current: bool = False


class SetupProgressOut(BaseModel):
    steps: list[SetupStepOut]
    completed_count: int
    total_count: int
    all_done: bool
    next_step_id: Optional[str] = None
    next_path: Optional[str] = None
    wizard_completed: bool = False
    # True when stored Proxmox/SMTP secrets fail Fernet decrypt (wrong SECRET_KEY)
    secrets_need_attention: bool = False
    secrets_message: Optional[str] = None
    # Offer wizard when not marked complete, or when secrets are broken (not forced)
    offer_wizard: bool = True
