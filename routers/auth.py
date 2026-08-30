"""Authentication-related endpoints: email verification and password reset.

Unlike accounts.py (actions on an already logged-in account), this covers
the auth flow itself — including endpoints that work without a fully
logged-in or verified user.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from config import API_BASE_URL, NO_REPLY_EMAIL, WEB_TEMPLATES_DIR
from database import get_db
from dependencies import get_current_user
from models.models import EmailVerificationToken, PasswordResetToken, Users
from rate_limit import limiter
from services.email.sender import send_email
from services.supabase_client import get_admin_client

router = APIRouter(prefix="/auth", tags=["auth"])

TOKEN_EXPIRY_MINUTES = 60


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_web_template(filename: str) -> str:
    return (WEB_TEMPLATES_DIR / filename).read_text(encoding="utf-8")


def _render_verify_email(
    template: str, card_class: str, icon: str, title: str, message: str
) -> HTMLResponse:
    html = (
        template.replace("{card_class}", card_class)
        .replace("{icon}", icon)
        .replace("{title}", title)
        .replace("{message}", message)
    )
    return HTMLResponse(html)


def _render_reset_password(
    template: str, card_class: str, content: str
) -> HTMLResponse:
    html = template.replace("{card_class}", card_class).replace("{content}", content)
    return HTMLResponse(html)


_RESET_FORM = """
<div class="icon">🔒</div>
<h1>Reset Your Password</h1>
<p class="subtitle">Choose a new password for your account.</p>
<form method="post">
    <input type="hidden" name="token" value="{token}">
    <label for="new_password">New password</label>
    <input type="password" id="new_password" name="new_password" required minlength="8">
    <label for="confirm_password">Confirm new password</label>
    <input type="password" id="confirm_password" name="confirm_password" required minlength="8">
    <button type="submit">Set New Password</button>
    {error}
</form>
"""


# --- Email verification ---


@router.post("/email-verification/request")
@limiter.limit("3/hour")
async def request_email_verification(
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate and send a verification link to the currently logged-in user.

    Uses get_current_user (not get_current_verified_user): an unverified
    user must be able to call this endpoint.
    """
    user = db.query(Users).filter_by(id=current_user.id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.email_verified:
        return {"detail": "Email already verified"}

    token = _generate_token()

    # Invalidate any existing unused tokens for this user
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None),
    ).update({"used_at": datetime.now(UTC).replace(tzinfo=None)})

    entry = EmailVerificationToken(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(UTC).replace(tzinfo=None)
        + timedelta(minutes=TOKEN_EXPIRY_MINUTES),
    )
    db.add(entry)
    db.commit()

    success = await send_email(
        to_address=user.email,
        from_address=NO_REPLY_EMAIL,
        subject="Verify Your PieceHunt Account",
        template_name="verify_email",
        username=user.email,
        verification_link=f"{API_BASE_URL}/auth/email-verification/confirm?token={token}",
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to send verification email")

    return {"detail": "Verification email sent"}


@router.get("/email-verification/status")
async def get_email_verification_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the email verification status of the currently logged-in user."""
    user = db.query(Users).filter_by(id=current_user.id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"email_verified": user.email_verified}


@router.get("/email-verification/confirm", response_class=HTMLResponse)
async def confirm_email_verification(
    token: str,
    db: Session = Depends(get_db),
):
    """Process the verification link from the email. No auth required — the token is the verification."""
    template = _load_web_template("verify_email.html")

    token_hash = _hash_token(token)

    entry = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
        )
        .first()
    )

    if not entry:
        return _render_verify_email(
            template,
            "error",
            "❌",
            "Invalid Link",
            "This verification link is invalid or has already been used.",
        )

    if entry.expires_at < datetime.now(UTC).replace(tzinfo=None):
        return _render_verify_email(
            template,
            "error",
            "❌",
            "Link Expired",
            "This verification link has expired. Please request a new one in the app.",
        )

    user = db.query(Users).filter_by(id=entry.user_id).first()
    if user is None:
        return _render_verify_email(
            template,
            "error",
            "❌",
            "Something Went Wrong",
            "We could not find your account. Please contact support.",
        )

    entry.used_at = datetime.now(UTC).replace(tzinfo=None)
    user.email_verified = True
    db.commit()

    admin_supabase = get_admin_client()
    admin_supabase.auth.admin.update_user_by_id(str(user.id), {"email_confirm": True})

    # Send welcome email (fire-and-forget, don't wait for it)
    await send_email(
        to_address=user.email,
        from_address=NO_REPLY_EMAIL,
        subject="Welcome To PieceHunt!",
        template_name="registration",
        username=user.email,
    )

    return _render_verify_email(
        template,
        "",
        "✅",
        "Email Verified!",
        "Your email address has been verified. You can now use PieceHunt.",
    )


# --- Password reset ---


class RequestPasswordReset(BaseModel):
    email: EmailStr


@router.post("/password-reset/request")
@limiter.limit("3/hour")
async def request_password_reset(
    request: Request, payload: RequestPasswordReset, db: Session = Depends(get_db)
):
    """No auth required: the user is by definition logged out or has forgotten their password.

    Always returns the same response regardless of whether the address exists,
    to prevent user enumeration.
    """
    user = db.query(Users).filter_by(email=payload.email).first()

    if user:
        token = _generate_token()

        # Invalidate any existing unused tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": datetime.now(UTC).replace(tzinfo=None)})

        entry = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(minutes=TOKEN_EXPIRY_MINUTES),
        )
        db.add(entry)
        db.commit()

        await send_email(
            to_address=user.email,
            from_address=NO_REPLY_EMAIL,
            subject="Password Reset — PieceHunt",
            template_name="password_reset",
            username=user.email,
            reset_link=f"{API_BASE_URL}/auth/password-reset/confirm?token={token}",
        )

    return {"detail": "If this email exists, a reset link has been sent"}


@router.get("/password-reset/confirm", response_class=HTMLResponse)
async def get_password_reset(token: str, db: Session = Depends(get_db)):
    """Show the password reset form if the token is valid."""
    template = _load_web_template("reset_password.html")

    token_hash = _hash_token(token)
    entry = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if not entry or entry.expires_at < datetime.now(UTC).replace(tzinfo=None):
        content = "<div class='icon'>❌</div><h1>Invalid or Expired Link</h1><p>This password reset link is invalid or has expired. Please request a new one.</p>"
        return _render_reset_password(template, "error", content)

    form_html = _RESET_FORM.format(token=token, error="")
    return _render_reset_password(template, "", form_html)


@router.post("/password-reset/confirm", response_class=HTMLResponse)
async def post_password_reset(
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Process the submitted password reset form."""
    template = _load_web_template("reset_password.html")

    def render_form(error: str) -> HTMLResponse:
        form_html = _RESET_FORM.format(
            token=token, error=f"<p class='error-msg'>{error}</p>"
        )
        return _render_reset_password(template, "", form_html)

    if new_password != confirm_password:
        return render_form("Passwords do not match.")

    if len(new_password) < 8:
        return render_form("Password must be at least 8 characters.")

    token_hash = _hash_token(token)
    entry = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if not entry or entry.expires_at < datetime.now(UTC).replace(tzinfo=None):
        content = "<div class='icon'>❌</div><h1>Invalid or Expired Link</h1><p>This password reset link is invalid or has expired. Please request a new one.</p>"
        return _render_reset_password(template, "error", content)

    user = db.query(Users).filter_by(id=entry.user_id).first()
    if user is None:
        content = "<div class='icon'>❌</div><h1>Something Went Wrong</h1><p>We could not find your account. Please contact support.</p>"
        return _render_reset_password(template, "error", content)

    entry.used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    admin_supabase = get_admin_client()
    admin_supabase.auth.admin.update_user_by_id(
        str(user.id), {"password": new_password}
    )

    content = "<div class='icon'>✅</div><h1>Password Updated!</h1><p>Your password has been changed. You can now log in with your new password.</p>"
    return _render_reset_password(template, "success", content)
