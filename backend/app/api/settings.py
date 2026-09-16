"""
Purpose: App settings, SMTP, dashboard, users list, setup progress endpoints.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-15
Version: 1.11.0
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.guests import _guest_out
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Guest, ProxmoxHost, RestoreRun, User
from app.schemas import (
    ActiveRunOut,
    AppSettingsOut,
    AppSettingsUpdate,
    DashboardOut,
    HeartbeatOut,
    HeartbeatUpdate,
    PurgeRunsOut,
    PurgeRunsRequest,
    PurgeStaleRunsOut,
    PurgeStaleRunsRequest,
    PushOut,
    PushUpdate,
    RunOut,
    SchedulePlanOut,
    SetupProgressOut,
    SetupStepOut,
    SmtpOut,
    SmtpTestRequest,
    SmtpUpdate,
    UserOut,
)
from app.security import decrypt_secret, encrypt_secret, hash_password
from app.services import locks
from app.services.bootstrap import (
    get_app_settings,
    get_heartbeat_settings,
    get_push_settings,
    get_smtp_settings,
)
from app.services.email_templates import apply_default_templates
from app.services.heartbeat import HeartbeatConfigError, send_heartbeat, validate_url
from app.services.mailer import apply_preset_defaults, send_email
from app.services.pusher import PushConfigError, send_push, split_topic_url
from app.services.remediation import remediation_for_runs, run_out_with_remediation
from app.services.retention import purge_runs_before, purge_stale_runs
from app.services.scheduler import build_schedule_plan, pick_next_guest, refresh_guest_due_times
from app.services.smtp_presets import list_presets

router = APIRouter(tags=["settings"])


def _secrets_health(db: Session) -> tuple[bool, str | None]:
    """Return (needs_attention, message) if Fernet cannot decrypt stored secrets."""
    broken: list[str] = []
    for host in db.query(ProxmoxHost).all():
        if not host.token_secret_enc:
            continue
        try:
            decrypt_secret(host.token_secret_enc)
        except ValueError:
            broken.append(f"host “{host.name}” API token")
    smtp = get_smtp_settings(db)
    if smtp.password_enc:
        try:
            decrypt_secret(smtp.password_enc)
        except ValueError:
            broken.append("SMTP password")
    push = get_push_settings(db)
    if push.token_enc:
        try:
            decrypt_secret(push.token_enc)
        except ValueError:
            broken.append("push access token")
    if not broken:
        return False, None
    detail = (
        "Stored secrets cannot be decrypted with the current SECRET_KEY: "
        + ", ".join(broken)
        + ". Re-enter those secrets on Hosts / Notifications, or restore the original SECRET_KEY."
    )
    return True, detail


def _smtp_out(s) -> SmtpOut:
    return SmtpOut(
        provider=s.provider,
        host=s.host,
        port=s.port,
        use_tls=s.use_tls,
        use_ssl=s.use_ssl,
        username=s.username,
        from_email=s.from_email,
        from_name=s.from_name,
        password_set=bool(s.password_enc),
        smtp_ok_at=s.smtp_ok_at,
    )


@router.get("/settings", response_model=AppSettingsOut)
def read_settings(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettingsOut:
    return get_app_settings(db)


@router.put("/settings", response_model=AppSettingsOut)
def update_settings(
    body: AppSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AppSettingsOut:
    settings = get_app_settings(db)
    data = body.model_dump(exclude_unset=True)
    if "schedule_coverage_goal" in data and data["schedule_coverage_goal"] is not None:
        goal = str(data["schedule_coverage_goal"]).lower().strip()
        if goal not in ("weekly", "monthly", "custom"):
            raise HTTPException(status_code=400, detail="coverage goal must be weekly, monthly, or custom")
        data["schedule_coverage_goal"] = goal
    if "schedule_batch_size" in data and data["schedule_batch_size"] is not None:
        data["schedule_batch_size"] = max(1, min(500, int(data["schedule_batch_size"])))
    if "gap_alert_hours" in data and data["gap_alert_hours"] is not None:
        data["gap_alert_hours"] = max(1, min(168, int(data["gap_alert_hours"])))
    for key, value in data.items():
        setattr(settings, key, value)
    db.commit()
    refresh_guest_due_times(db)
    return settings


@router.post("/settings/email-templates/reset", response_model=AppSettingsOut)
def reset_email_templates(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> AppSettingsOut:
    settings = get_app_settings(db)
    apply_default_templates(settings)
    db.commit()
    return settings


@router.post("/settings/purge-runs", response_model=PurgeRunsOut)
def purge_runs(
    body: PurgeRunsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PurgeRunsOut:
    """Admin: delete restore run history (and evidence files) older than a cutoff."""
    before = body.before
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if before >= now:
        raise HTTPException(
            status_code=400,
            detail="Cutoff must be in the past — refuse to purge current/future runs",
        )
    deleted = purge_runs_before(db, before)
    return PurgeRunsOut(deleted=deleted, before=before)


@router.post("/settings/purge-stale-runs", response_model=PurgeStaleRunsOut)
def purge_stale(
    body: PurgeStaleRunsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PurgeStaleRunsOut:
    """Admin: delete runs for removed guests and/or guests not in a backup job."""
    if not body.orphaned and not body.not_backed_up:
        raise HTTPException(
            status_code=400,
            detail="Select at least one category: orphaned and/or not_backed_up",
        )
    total, orphaned_n, not_backed_n = purge_stale_runs(
        db, orphaned=body.orphaned, not_backed_up=body.not_backed_up
    )
    return PurgeStaleRunsOut(
        deleted=total,
        orphaned_deleted=orphaned_n,
        not_backed_up_deleted=not_backed_n,
    )


@router.get("/schedule/plan", response_model=SchedulePlanOut)
def schedule_plan(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> SchedulePlanOut:
    return SchedulePlanOut(**build_schedule_plan(db))


@router.get("/smtp/presets")
def smtp_presets(_: User = Depends(get_current_user)) -> list:
    return list_presets()


@router.get("/smtp", response_model=SmtpOut)
def read_smtp(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> SmtpOut:
    return _smtp_out(get_smtp_settings(db))


@router.put("/smtp", response_model=SmtpOut)
def update_smtp(
    body: SmtpUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SmtpOut:
    data = apply_preset_defaults(body.provider, body.model_dump())
    s = get_smtp_settings(db)
    s.provider = body.provider
    s.host = data.get("host") or body.host
    s.port = data.get("port") or body.port
    s.use_tls = body.use_tls
    s.use_ssl = body.use_ssl
    s.username = data.get("username") or body.username
    s.from_email = body.from_email
    s.from_name = body.from_name
    if body.password:
        s.password_enc = encrypt_secret(body.password)
        s.smtp_ok_at = None
    db.commit()
    return _smtp_out(s)


@router.post("/smtp/test")
async def test_smtp(
    body: SmtpTestRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        await send_email(
            db,
            to_addrs=[body.to_email],
            subject="RestoreProof SMTP test",
            body="This is a test email from RestoreProof. SMTP is working.",
        )
    except Exception as exc:  # noqa: BLE001
        s = get_smtp_settings(db)
        s.smtp_ok_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    s = get_smtp_settings(db)
    s.smtp_ok_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


def _push_out(p) -> PushOut:
    return PushOut(
        enabled=p.enabled,
        provider=p.provider,
        url=p.url,
        verify_ssl=p.verify_ssl,
        on_success=p.on_success,
        on_failure=p.on_failure,
        token_set=bool(p.token_enc),
        push_ok_at=p.push_ok_at,
    )


@router.get("/push", response_model=PushOut)
def read_push(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> PushOut:
    return _push_out(get_push_settings(db))


@router.put("/push", response_model=PushOut)
def update_push(
    body: PushUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PushOut:
    p = get_push_settings(db)
    data = body.model_dump(exclude_unset=True)
    token = data.pop("token", None)

    # Only a malformed URL is worth rejecting. Enabling before a topic exists is a
    # normal in-progress state — it saves, and _push_run simply sends nothing.
    if data.get("url"):
        try:
            split_topic_url(data["url"])
        except PushConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for key, value in data.items():
        if value is not None:
            setattr(p, key, value)
    if token is not None:
        # "-" clears a stored token; blank leaves it untouched.
        if token.strip() == "-":
            p.token_enc = ""
        elif token.strip():
            p.token_enc = encrypt_secret(token.strip())
        p.push_ok_at = None
    db.commit()
    return _push_out(p)


@router.post("/push/test")
async def test_push(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    app_settings = get_app_settings(db)
    try:
        await send_push(
            db,
            title=f"{app_settings.branding_title} test",
            message="Push notifications are working. Restore test alerts will arrive here.",
            priority="default",
            tags=["bell"],
            click_url=get_settings().app_base_url.rstrip("/"),
        )
    except Exception as exc:  # noqa: BLE001
        p = get_push_settings(db)
        p.push_ok_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    p = get_push_settings(db)
    p.push_ok_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/heartbeat", response_model=HeartbeatOut)
def read_heartbeat(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> HeartbeatOut:
    return HeartbeatOut.model_validate(get_heartbeat_settings(db))


@router.put("/heartbeat", response_model=HeartbeatOut)
def update_heartbeat(
    body: HeartbeatUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> HeartbeatOut:
    h = get_heartbeat_settings(db)
    data = body.model_dump(exclude_unset=True)
    # As with push: reject only a malformed URL, never an incomplete draft.
    if data.get("url"):
        try:
            data["url"] = validate_url(data["url"])
        except HeartbeatConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for key, value in data.items():
        if value is not None:
            setattr(h, key, value)
    db.commit()
    return HeartbeatOut.model_validate(h)


@router.post("/heartbeat/test")
def test_heartbeat(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Ping now regardless of interval, and record the outcome."""
    h = get_heartbeat_settings(db)
    try:
        send_heartbeat(db)
    except Exception as exc:  # noqa: BLE001
        h.last_error = str(exc)[:500]
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    h.last_ping_at = datetime.now(timezone.utc)
    h.last_error = ""
    db.commit()
    return {"ok": True}


@router.get("/setup/progress", response_model=SetupProgressOut)
def setup_progress(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> SetupProgressOut:
    settings = get_app_settings(db)
    smtp = get_smtp_settings(db)
    hosts = db.query(ProxmoxHost).all()
    guest_count = db.query(Guest).count()
    success_runs = db.query(RestoreRun).filter(RestoreRun.status == "success").count()
    any_runs = db.query(RestoreRun).count()
    secrets_need_attention, secrets_message = _secrets_health(db)

    admin_done = db.query(User).count() > 0
    smtp_done = bool(smtp.smtp_ok_at) or (
        bool(smtp.host) and bool(smtp.from_email) and bool(smtp.password_enc)
    )
    # Host step not done if tokens cannot be decrypted
    host_done = (not secrets_need_attention) and any(
        h.api_ok_at and h.ssh_ok_at for h in hosts
    )
    sync_done = any(h.last_sync_at for h in hosts) or guest_count > 0
    manual_done = success_runs > 0 or any_runs > 0
    schedule_done = bool(settings.schedule_enabled)

    host_body = (
        "API token + SSH key. Use Test API and Test SSH until both are green."
        if not secrets_need_attention
        else "SECRET_KEY mismatch: re-enter the Proxmox API token secret, then Test API / SSH."
    )

    raw = [
        SetupStepOut(
            id="admin",
            title="1. Admin account",
            body="Created at first login. Enable 2FA under Users when ready.",
            to="/users",
            done=admin_done,
        ),
        SetupStepOut(
            id="smtp",
            title="2. SMTP notifications",
            body=(
                "Pick a provider preset and send a test email."
                if not secrets_need_attention
                else "If mail fails after a SECRET_KEY change, re-enter the SMTP password."
            ),
            to="/notifications",
            done=smtp_done and not (
                secrets_need_attention and "SMTP" in (secrets_message or "")
            ),
        ),
        SetupStepOut(
            id="host",
            title="3. Add Proxmox host",
            body=host_body,
            to="/hosts",
            done=host_done,
        ),
        SetupStepOut(
            id="sync",
            title="4. Sync guests",
            body="Pull VM/CT inventory from the host. Token needs list rights (Privilege Separation off, or ACL).",
            to="/hosts",
            done=sync_done,
        ),
        SetupStepOut(
            id="manual",
            title="5. Run a manual test",
            body="Use Run now on a non-critical guest. Review the screenshot on Runs.",
            to="/guests",
            done=manual_done,
        ),
        SetupStepOut(
            id="schedule",
            title="6. Enable schedule",
            body="Turn on the global cron once manual drills look good.",
            to="/schedule",
            done=schedule_done,
        ),
    ]

    next_id = None
    next_path = None
    for step in raw:
        if not step.done:
            next_id = step.id
            next_path = step.to
            break
    steps = [
        SetupStepOut(
            id=s.id,
            title=s.title,
            body=s.body,
            to=s.to,
            done=s.done,
            current=s.id == next_id,
        )
        for s in raw
    ]
    completed = sum(1 for s in steps if s.done)
    wizard_completed = bool(getattr(settings, "setup_wizard_completed", False))
    offer_wizard = (not wizard_completed) or secrets_need_attention
    return SetupProgressOut(
        steps=steps,
        completed_count=completed,
        total_count=len(steps),
        all_done=completed == len(steps) and not secrets_need_attention,
        next_step_id=next_id,
        next_path=next_path,
        wizard_completed=wizard_completed,
        secrets_need_attention=secrets_need_attention,
        secrets_message=secrets_message,
        offer_wizard=offer_wizard,
    )


@router.post("/setup/wizard/complete")
def setup_wizard_complete(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Mark the guided setup checklist as completed (can re-offer if secrets break)."""
    settings = get_app_settings(db)
    settings.setup_wizard_completed = True
    db.commit()
    return {"ok": True, "setup_wizard_completed": True}


@router.post("/setup/wizard/reopen")
def setup_wizard_reopen(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Show the guided setup checklist again without resetting admin setup."""
    settings = get_app_settings(db)
    settings.setup_wizard_completed = False
    db.commit()
    return {"ok": True, "setup_wizard_completed": False}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    recent_limit: int = Query(
        10, ge=0, le=500, description="Recent runs to return; 0 returns all"
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardOut:
    settings = get_app_settings(db)
    lock = locks.get_lock(db)
    recent_query = db.query(RestoreRun).order_by(RestoreRun.created_at.desc())
    if recent_limit:
        recent_query = recent_query.limit(recent_limit)
    recent = recent_query.all()
    remediated_by = remediation_for_runs(db, recent)
    active = (
        db.query(RestoreRun)
        .filter(RestoreRun.status.in_(("queued", "running")))
        .order_by(RestoreRun.id.desc())
        .first()
    )
    active_out = None
    if active:
        active_out = ActiveRunOut(
            id=active.id,
            status=active.status,
            source_name=active.source_name,
            source_vmid=active.source_vmid,
            guest_type=active.guest_type,
            host_id=active.host_id,
            test_vmid=active.test_vmid,
            progress_pct=active.progress_pct if active.progress_pct is not None else (
                0.0 if active.status == "queued" else None
            ),
            progress_label=active.progress_label
            or ("Queued" if active.status == "queued" else "In progress"),
            started_at=active.started_at,
            created_at=active.created_at,
        )
    next_guest = pick_next_guest(db) if settings.schedule_enabled else None
    next_out = None
    if next_guest:
        host = db.query(ProxmoxHost).filter_by(id=next_guest.host_id).first()
        latest = (
            db.query(RestoreRun)
            .filter(RestoreRun.guest_id == next_guest.id)
            .order_by(RestoreRun.id.desc())
            .first()
        )
        next_out = _guest_out(next_guest, host.name if host else "", latest)
    return DashboardOut(
        setup_completed=settings.setup_completed,
        schedule_enabled=settings.schedule_enabled,
        global_cron=settings.global_cron,
        lock_held=bool(lock.held_by),
        lock_held_by=lock.held_by,
        lock_run_id=lock.run_id,
        recent_runs=[run_out_with_remediation(r, remediated_by) for r in recent],
        recent_runs_total=db.query(RestoreRun).count(),
        guest_count=db.query(Guest).count(),
        excluded_count=db.query(Guest).filter(Guest.excluded.is_(True)).count(),
        host_count=db.query(ProxmoxHost).count(),
        next_due=next_out,
        active_run=active_out,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list:
    return db.query(User).order_by(User.id).all()


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/users", response_model=UserOut)
def create_user(
    body: CreateUserRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> User:
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
