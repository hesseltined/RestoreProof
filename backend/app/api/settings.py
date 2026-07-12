"""
Purpose: App settings, SMTP, dashboard, users list, setup progress endpoints.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.2.0
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Guest, ProxmoxHost, RestoreRun, User
from app.schemas import (
    ActiveRunOut,
    AppSettingsOut,
    AppSettingsUpdate,
    DashboardOut,
    GuestOut,
    RunOut,
    SchedulePlanOut,
    SetupProgressOut,
    SetupStepOut,
    SmtpOut,
    SmtpTestRequest,
    SmtpUpdate,
    UserOut,
)
from app.security import encrypt_secret, hash_password
from app.services import locks
from app.services.bootstrap import get_app_settings, get_smtp_settings
from app.services.mailer import apply_preset_defaults, send_email
from app.services.scheduler import build_schedule_plan, pick_next_guest, refresh_guest_due_times
from app.services.smtp_presets import list_presets

router = APIRouter(tags=["settings"])


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
    for key, value in data.items():
        setattr(settings, key, value)
    db.commit()
    refresh_guest_due_times(db)
    return settings


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

    admin_done = db.query(User).count() > 0
    smtp_done = bool(smtp.smtp_ok_at) or (
        bool(smtp.host) and bool(smtp.from_email) and bool(smtp.password_enc)
    )
    host_done = any(h.api_ok_at and h.ssh_ok_at for h in hosts)
    sync_done = any(h.last_sync_at for h in hosts) or guest_count > 0
    manual_done = success_runs > 0 or any_runs > 0
    schedule_done = bool(settings.schedule_enabled)

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
            body="Pick a provider preset and send a test email.",
            to="/notifications",
            done=smtp_done,
        ),
        SetupStepOut(
            id="host",
            title="3. Add Proxmox host",
            body="API token + SSH key. Use Test API and Test SSH until both are green.",
            to="/hosts",
            done=host_done,
        ),
        SetupStepOut(
            id="sync",
            title="4. Sync guests",
            body="Pull VM/CT inventory from the host, then return here.",
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
    return SetupProgressOut(
        steps=steps,
        completed_count=completed,
        total_count=len(steps),
        all_done=completed == len(steps),
        next_step_id=next_id,
        next_path=next_path,
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> DashboardOut:
    settings = get_app_settings(db)
    lock = locks.get_lock(db)
    recent = (
        db.query(RestoreRun).order_by(RestoreRun.created_at.desc()).limit(10).all()
    )
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
        next_out = GuestOut(
            id=next_guest.id,
            host_id=next_guest.host_id,
            host_name=host.name if host else "",
            vmid=next_guest.vmid,
            name=next_guest.name,
            guest_type=next_guest.guest_type,
            node=next_guest.node,
            status=next_guest.status,
            excluded=next_guest.excluded,
            schedule_cron=next_guest.schedule_cron,
            schedule_enabled=next_guest.schedule_enabled,
            last_tested_at=next_guest.last_tested_at,
            next_due_at=next_guest.next_due_at,
        )
    return DashboardOut(
        setup_completed=settings.setup_completed,
        schedule_enabled=settings.schedule_enabled,
        global_cron=settings.global_cron,
        lock_held=bool(lock.held_by),
        lock_held_by=lock.held_by,
        lock_run_id=lock.run_id,
        recent_runs=[RunOut.model_validate(r) for r in recent],
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
