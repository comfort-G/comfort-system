# app/routers/admin_members.py
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import logging
from pathlib import Path
import re
from passlib.context import CryptContext
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.repositories import family_repo, home_repository
from app.services import admin_member_service
from fastapi.responses import RedirectResponse, HTMLResponse
from psycopg2.errors import UniqueViolation

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
router = APIRouter(prefix="/api/admin/members", tags=["Admin Member Management"])
account_router = APIRouter(prefix="/api/admin", tags=["Admin Member Management"])
logger = logging.getLogger(__name__)
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class StatusOverrideRequest(BaseModel):
    override_status: Optional[str] = None  # Pass null/None to clear override and return to system automatic status


class AccountSuspensionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class MemberAccountUpsertRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=200)
    phone_number: str = Field(min_length=1, max_length=20)
    email: str = Field(min_length=3, max_length=254)
    raw_password: str = Field(min_length=8, max_length=72)
    role: str = "member"

    @field_validator("member_id", "full_name", "phone_number", "email")
    @classmethod
    def strip_required_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("raw_password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes.")
        return value

    @field_validator("role")
    @classmethod
    def validate_member_role(cls, value: str) -> str:
        if value.strip().casefold() != "member":
            raise ValueError("This endpoint can only create or update member accounts.")
        return "Member"


@account_router.post("/create-member")
def create_or_reset_member_account(
    payload: MemberAccountUpsertRequest,
    current_user: dict = Depends(get_current_user),
):
    if (current_user.get("role") or "").strip().casefold() not in {
        "chairperson",
        "secretary",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the Chairperson or Secretary can create or reset member accounts.",
        )

    password_hash = password_context.hash(payload.raw_password)
    email_in_use = False
    member = None
    try:
        with get_db() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM public.members
                WHERE LOWER(BTRIM(email)) = LOWER(BTRIM(%s))
                  AND LOWER(BTRIM(member_id)) <> LOWER(BTRIM(%s))
                LIMIT 1;
                """,
                (payload.email, payload.member_id),
            )
            email_in_use = cursor.fetchone() is not None
            if not email_in_use:
                cursor.execute(
                    """
                    INSERT INTO public.members (
                        member_id,
                        full_name,
                        email,
                        phone,
                        password_hash,
                        role,
                        status,
                        must_change_password
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'Active', TRUE)
                    ON CONFLICT (member_id)
                    DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        phone = EXCLUDED.phone,
                        full_name = EXCLUDED.full_name,
                        email = EXCLUDED.email,
                        role = EXCLUDED.role,
                        must_change_password = TRUE,
                        reset_token = NULL,
                        reset_expires_at = NULL,
                        token_version = public.members.token_version + 1
                    RETURNING member_id;
                    """,
                    (
                        payload.member_id,
                        payload.full_name,
                        payload.email,
                        payload.phone_number,
                        password_hash,
                        payload.role,
                    ),
                )
                member = cursor.fetchone()
    except UniqueViolation as exc:
        if exc.diag.constraint_name == "members_email_key":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email address is already assigned to another member. Use a unique email address.",
            ) from exc
        raise

    if email_in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is already assigned to another member. Use a unique email address.",
        )

    if member is None:
        logger.error("Member account upsert returned no member ID.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The member account could not be saved.",
        )

    return {
        "status": "success",
        "message": f"Member account created or password reset for {member['member_id']}.",
    }


@router.get("/view", response_class=RedirectResponse)
def render_admin_members_page(
    _: dict = Depends(require_role(["Chairperson", "Secretary", "Treasurer"])),
):
    """Keep the former status page URL working while centralizing executive actions."""
    return RedirectResponse(url="/api/executive-actions/view", status_code=307)

def _member_profile_details_context(member_id: str, *, is_admin: bool = False):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                member_id,
                full_name,
                phone,
                email,
                address,
                occupation,
                date_of_birth,
                next_of_kin_name,
                next_of_kin_relationship,
                next_of_kin_phone,
                status,
                override_status,
                role,
                avatar_url,
                joined_date,
                join_date,
                must_change_password,
                suspended_at,
                suspension_reason
            FROM public.members
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found.")
        cursor.execute(
            """
            SELECT member_id, full_name
            FROM public.members
            ORDER BY full_name, member_id;
            """
        )
        all_members = cursor.fetchall()

    financials = home_repository.fetch_home_records(member_id, include_global_financials=False)
    member_financials = financials.get("member_financials") if financials else {}
    relatives = family_repo.get_relatives_by_member(member_id)
    required_fields = [
        ("phone", "Phone number"),
        ("email", "Email address"),
        ("address", "Home address"),
        ("occupation", "Occupation"),
        ("date_of_birth", "Date of birth"),
        ("next_of_kin_name", "Next of kin name"),
        ("next_of_kin_relationship", "Next of kin relationship"),
        ("next_of_kin_phone", "Next of kin phone number"),
    ]
    missing_fields = []
    for field_name, label in required_fields:
        if not member.get(field_name):
            missing_fields.append(label)
    return {
        "member": member,
        "member_id": member["member_id"],
        "full_name": member["full_name"],
        "financial_summary": member_financials or {},
        "relatives": relatives,
        "missing_fields": missing_fields,
        "all_members": all_members,
        "is_admin": is_admin,
    }


@router.get("/status-report")
def get_member_status_report(
    _: dict = Depends(require_role(["Chairperson", "Secretary", "Treasurer"]))
):
    """API endpoint for executives to view automatic and final member status classifications."""
    report = admin_member_service.evaluate_member_statuses()
    return {
        "status": "success",
        "total_members": len(report),
        "data": report
    }


@router.get("/profile", response_class=HTMLResponse)
@router.get("/profile/{member_str_id}", response_class=HTMLResponse)
def render_member_profile_and_relatives_page(
    request: Request,
    member_str_id: str | None = None,
    _: dict = Depends(require_role(["Chairperson", "Secretary", "Treasurer"])),
):
    """Admin-only consolidated page showing a member's identity, status, finances, and relatives."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT member_id, full_name
            FROM public.members
            ORDER BY full_name, member_id;
            """
        )
        members = cursor.fetchall()
    selected_member_id = member_str_id or (members[0]["member_id"] if members else None)
    if selected_member_id is None:
        return templates.TemplateResponse(
            request=request,
            name="member_profile_details.html",
            context={
                "request": request,
                "member": None,
                "all_members": [],
                "financial_summary": {},
                "relatives": [],
                "missing_fields": [],
                "is_admin": True,
                "page_title": "Member Profile & Relatives",
                "page_intro": "No member records are available yet.",
            },
        )
    context = _member_profile_details_context(selected_member_id, is_admin=True)
    context["request"] = request
    context["page_title"] = "Member Profile & Relatives"
    context["page_intro"] = "Profile details, account status, finances, and registered relatives in one place."
    return templates.TemplateResponse(
        request=request,
        name="member_profile_details.html",
        context=context,
    )


@router.put("/{member_str_id}/override-status")
def chairperson_override_status(
    member_str_id: str,
    payload: StatusOverrideRequest,
    _: dict = Depends(require_role(["Chairperson"]))  # STRICTLY CHAIRPERSON ONLY
):
    """API endpoint allowing ONLY the Chairperson to override a member's system status."""
    try:
        response = admin_member_service.chair_override_member_status(member_str_id, payload.override_status)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{member_str_id}/suspend")
def suspend_member_account(
    member_str_id: str,
    payload: AccountSuspensionRequest,
    _: dict = Depends(require_role(["Chairperson"])),
):
    try:
        return admin_member_service.suspend_member_account(
            member_str_id=member_str_id,
            reason=payload.reason,
            actor_id=_["member_id"],
            actor_name=_.get("full_name") or _["member_id"],
            actor_role=_.get("role", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{member_str_id}/restore")
def restore_member_account(
    member_str_id: str,
    payload: AccountSuspensionRequest,
    _: dict = Depends(require_role(["Chairperson"])),
):
    try:
        return admin_member_service.restore_member_account(
            member_str_id=member_str_id,
            reason=payload.reason,
            actor_id=_["member_id"],
            actor_name=_.get("full_name") or _["member_id"],
            actor_role=_.get("role", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc