"""
Purpose: Pydantic request/response schemas.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.3.0
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


class SchedulePlanOut(BaseModel):
    """Planning numbers for coverage / batch sizing (excludes excluded guests)."""

    total_guests: int
    excluded_count: int
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


class GuestOut(BaseModel):
    id: int
    host_id: int
    host_name: str = ""
    vmid: int
    name: str
    guest_type: str
    node: str
    status: str
    excluded: bool
    schedule_cron: Optional[str]
    schedule_enabled: bool
    last_tested_at: Optional[datetime]
    next_due_at: Optional[datetime]

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

    model_config = {"from_attributes": True}


class RunDetail(RunOut):
    log_text: str


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
