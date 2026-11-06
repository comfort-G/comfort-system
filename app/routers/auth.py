# app/routers/auth.py
import asyncio
import html
import hashlib
import logging
import os
import secrets
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator
import bcrypt
from psycopg2 import InterfaceError, OperationalError
from app.database import get_db
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.dependencies import get_current_user
from app.limiter import limiter
from app.repositories.admin_member_repo import notify_executives_of_suspended_login
from app.security import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
)


templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("uvicorn")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
password_reset_page_router = APIRouter(tags=["Authentication"])
COOKIE_SECURE = settings.ENVIRONMENT in {"production", "prod"}
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_RESET_MESSAGE = (
    "If an account matches that identifier, password reset instructions have been "
    "dispatched to your registered email."
)


def _password_reset_base_url() -> str:
    return (
        os.getenv("PASSWORD_RESET_PUBLIC_URL")
        or settings.PASSWORD_RESET_PUBLIC_URL
        or "http://localhost:8000"
    ).rstrip("/")


class LoginRequest(BaseModel):
    identifier: str  # Can be member_id (e.g., "MEM001") or email
    password: str


class ForgotPasswordRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=6, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_bcrypt_byte_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes.")
        return value


def _send_email(to_email: str, reset_link: str) -> None:
    public_base_url = _password_reset_base_url()
    smtp_user = settings.SMTP_USER
    smtp_password = settings.SMTP_PASSWORD
    sender_email = settings.SENDER_EMAIL
    if not public_base_url or not smtp_user or not smtp_password or not sender_email:
        logger.warning(
            "Password reset email was not sent because SMTP settings are incomplete."
        )
        return

    public_url = urlsplit(public_base_url)
    allowed_http_localhost = public_url.hostname in {"localhost", "127.0.0.1"}
    if (
        public_url.scheme != "https" and not allowed_http_localhost
    ) or not public_url.netloc or public_url.username or public_url.password:
        logger.error(
            "Password reset email was not sent because the configured public URL is invalid."
        )
        return

    escaped_link = html.escape(reset_link, quote=True)
    message = MIMEMultipart("alternative")
    message["Subject"] = "Reset your Comfort Group Portal password"
    message["From"] = sender_email
    message["To"] = to_email
    message.attach(
        MIMEText(
            "A password reset was requested for your Comfort Group Portal account.\n\n"
            f"Use this link within 15 minutes to choose a new password:\n{reset_link}\n\n"
            "If you did not request this, you can ignore this message.",
            "plain",
            "utf-8",
        )
    )
    message.attach(
        MIMEText(
            "<html><body>"
            "<p>A password reset was requested for your Comfort Group Portal account.</p>"
            f'<p><a href="{escaped_link}">Reset your password</a></p>'
            "<p>This link expires in 15 minutes. If you did not request this, "
            "you can ignore this message.</p>"
            "</body></html>",
            "html",
            "utf-8",
        )
    )

    try:
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.sendmail(sender_email, [to_email], message.as_string())
        logger.info("Password reset email sent to the member's registered address.")
    except (OSError, smtplib.SMTPException):
        logger.exception("Password reset email delivery failed.")


async def send_email_notification(to_email: str, reset_link: str) -> None:
    await asyncio.to_thread(_send_email, to_email, reset_link)


@router.get("/page", response_class=HTMLResponse)
def render_login_page(request: Request):
    """Renders the HTML login frontend page."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request},
    )


@password_reset_page_router.get("/reset-password", response_class=HTMLResponse)
def render_reset_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"request": request},
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
):
    token = secrets.token_urlsafe(24)
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    identifier = payload.member_id.strip()

    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE public.members
            SET reset_token = %s,
                reset_expires_at =
                    (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + INTERVAL '15 minutes'
            WHERE id = (
                SELECT id
                FROM public.members
                WHERE LOWER(BTRIM(member_id)) = LOWER(BTRIM(%s))
                   OR LOWER(BTRIM(email)) = LOWER(BTRIM(%s))
                ORDER BY CASE
                    WHEN LOWER(BTRIM(member_id)) = LOWER(BTRIM(%s)) THEN 0
                    ELSE 1
                END
                LIMIT 1
            )
              AND email IS NOT NULL
              AND BTRIM(email) <> ''
            RETURNING email;
            """,
            (token_digest, identifier, identifier, identifier),
        )
        member = cursor.fetchone()

    if member:
        public_url = _password_reset_base_url()
        reset_link = f"{public_url}/reset-password?token={token}"
        background_tasks.add_task(
            send_email_notification,
            member["email"],
            reset_link,
        )

    return {"message": PASSWORD_RESET_MESSAGE}


@router.post("/reset-password-submit")
@limiter.limit("3/minute")
def reset_password_submit(request: Request, payload: ResetPasswordRequest):
    token_digest = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    password_hash = password_context.hash(payload.new_password)

    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE public.members
            SET password_hash = %s,
                must_change_password = FALSE,
                token_version = token_version + 1,
                reset_token = NULL,
                reset_expires_at = NULL
            WHERE reset_token = %s
              AND reset_expires_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            RETURNING id;
            """,
            (password_hash, token_digest),
        )
        member = cursor.fetchone()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link is invalid or has expired. Request a new one.",
        )

    return {"status": "success", "message": "Password reset successfully."}


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, credentials: LoginRequest, response: Response):
    """
    Authenticates a user against the existing Neon members table using member_id or email,
    verifies their bcrypt password hash, and sets a secure session cookie.
    """
    user = None
    identifier = credentials.identifier.strip()
    try:
        for attempt in range(2):
            try:
                with get_db() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            id, member_id, full_name, email, password_hash, role,
                            status, must_change_password, token_version
                        FROM public.members
                        WHERE LOWER(BTRIM(member_id)) = LOWER(BTRIM(%s))
                           OR LOWER(BTRIM(email)) = LOWER(BTRIM(%s))
                        ORDER BY CASE
                            WHEN LOWER(BTRIM(member_id)) = LOWER(BTRIM(%s)) THEN 0
                            ELSE 1
                        END
                        LIMIT 1;
                        """,
                        (identifier, identifier, identifier)
                    )
                    user = cursor.fetchone()
                break
            except (OperationalError, InterfaceError):
                if attempt == 1:
                    raise

        logger.info(
            "Login diagnostics: member_found=%s.",
            user is not None,
        )
        if not user:
            logger.info(
                "Login diagnostics: password_hash_exists=False, "
                "password_verified=False (verification not attempted)."
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid member ID/email or password"
            )

        stored_hash = user.get("password_hash")
        logger.info(
            "Login diagnostics: password_hash_exists=%s.",
            bool(stored_hash),
        )
        if not stored_hash:
            logger.info(
                "Login diagnostics: password_verified=False "
                "(verification not attempted)."
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password not set for this account."
            )

        try:
            stored_hash_bytes = (
                stored_hash.encode("utf-8")
                if isinstance(stored_hash, str)
                else bytes(stored_hash)
            )
            is_valid = bcrypt.checkpw(
                credentials.password.encode("utf-8"),
                stored_hash_bytes,
            )
        except (TypeError, ValueError):
            is_valid = False

        logger.info(
            "Login diagnostics: password_verified=%s.",
            is_valid,
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid member ID/email or password"
            )

        if (user.get("status") or "").strip().casefold() == "suspended":
            notified = notify_executives_of_suspended_login(
                user.get("member_id") or credentials.identifier,
                user.get("full_name") or "Member",
            )
            if not notified:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Your account is suspended. Please contact an executive; "
                        "the system could not deliver the executive alert."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is suspended. Please contact an executive for assistance."
            )

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=create_session_token(user["id"], user["token_version"]),
            httponly=True,
            secure=True if COOKIE_SECURE else False,
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS,
        )

        return {
            "status": "success",
            "message": "Login successful",
            "user": {
                "id": user["id"],
                "member_id": user.get("member_id"),
                "email": user.get("email"),
                "role": user.get("role"),
                "must_change_password": bool(user.get("must_change_password")),
            }
        }
    except (OperationalError, InterfaceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable. Please try again.",
        ) from exc

@router.get("/me")
def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    return {"user": current_user}


@router.post("/logout")
def logout(response: Response):
    """Clears the session cookie to log the user out."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=True if COOKIE_SECURE else False,
        samesite="lax",
    )
    return {"status": "success", "message": "Logged out successfully"}