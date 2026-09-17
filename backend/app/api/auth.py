"""
Purpose: Auth, setup, password reset, TOTP endpoints.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-17
Version: 1.1.0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import PasswordResetToken, User
from app.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SetupAdminRequest,
    StatusOut,
    TokenResponse,
    TotpEnableRequest,
    TotpSetupOut,
    UserOut,
)
from app.security import (
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.services.bootstrap import ensure_defaults, get_app_settings, public_app_url
from app.services.mailer import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=StatusOut)
def status_endpoint(db: Session = Depends(get_db)) -> StatusOut:
    ensure_defaults(db)
    settings = get_app_settings(db)
    return StatusOut(
        setup_completed=settings.setup_completed,
        user_count=db.query(User).count(),
    )


@router.post("/setup", response_model=TokenResponse)
def setup_admin(body: SetupAdminRequest, db: Session = Depends(get_db)) -> TokenResponse:
    ensure_defaults(db)
    settings = get_app_settings(db)
    if db.query(User).count() > 0:
        raise HTTPException(status_code=400, detail="Setup already completed")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        is_admin=True,
    )
    db.add(user)
    settings.setup_completed = True
    db.commit()
    token = create_access_token(user.email)
    return TokenResponse(access_token=token, setup_required=False)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    ensure_defaults(db)
    settings = get_app_settings(db)
    if db.query(User).count() == 0:
        return TokenResponse(access_token="", setup_required=True)

    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account disabled")

    if user.totp_enabled:
        if not body.totp_code:
            return TokenResponse(access_token="", requires_2fa=True)
        if not user.totp_secret or not verify_totp(user.totp_secret, body.totp_code):
            raise HTTPException(status_code=401, detail="Invalid 2FA code")
    elif settings.enforce_2fa:
        # Allow login but frontend should force 2FA enrollment
        pass

    token = create_access_token(user.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password-reset/request")
async def password_reset_request(
    body: PasswordResetRequest, db: Session = Depends(get_db)
) -> dict:
    user = db.query(User).filter(User.email == body.email.lower()).first()
    # Always return OK to avoid enumeration
    if not user:
        return {"ok": True}
    raw, token_hash = generate_reset_token()
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=get_settings().reset_token_expire_minutes
    )
    db.add(
        PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires)
    )
    db.commit()
    reset_url = f"{public_app_url(get_app_settings(db))}/reset-password?token={raw}"
    try:
        await send_email(
            db,
            to_addrs=[user.email],
            subject="RestoreProof password reset",
            body=f"Use this link to reset your password (expires soon):\n\n{reset_url}\n",
        )
    except Exception:
        # Still return ok; admin may not have SMTP yet
        return {"ok": True, "dev_reset_url": reset_url}
    return {"ok": True}


@router.post("/password-reset/confirm")
def password_reset_confirm(
    body: PasswordResetConfirm, db: Session = Depends(get_db)
) -> dict:
    token_hash = hash_token(body.token)
    row = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used.is_(False),
        )
        .first()
    )
    if not row or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = db.query(User).filter_by(id=row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid token")
    user.password_hash = hash_password(body.new_password)
    row.used = True
    db.commit()
    return {"ok": True}


@router.post("/totp/setup", response_model=TotpSetupOut)
def totp_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TotpSetupOut:
    secret = new_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/totp/enable")
def totp_enable(
    body: TotpEnableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /totp/setup first")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    user.totp_enabled = True
    db.commit()
    return {"ok": True}


@router.post("/totp/disable")
def totp_disable(
    body: TotpEnableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.totp_enabled and user.totp_secret and not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    return {"ok": True}
