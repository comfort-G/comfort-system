import logging
import re
from datetime import date
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from psycopg2.errors import UniqueViolation

from app.database import get_db
from app.dependencies import get_current_user
from app.repositories import family_repo, home_repository
from app.services import home_gallery_service


logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
router = APIRouter(prefix="/api/profile", tags=["Member Profile"])


class MemberProfileUpdate(BaseModel):
    phone: str = Field(min_length=1, max_length=20)
    email: str = Field(min_length=3, max_length=254)
    address: str | None = Field(default=None, max_length=500)
    occupation: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    next_of_kin_name: str | None = Field(default=None, max_length=120)
    next_of_kin_relationship: str | None = Field(default=None, max_length=80)
    next_of_kin_phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Phone number is required.")
        return value

    @field_validator(
        "address",
        "occupation",
        "next_of_kin_name",
        "next_of_kin_relationship",
        "next_of_kin_phone",
    )
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned_value = value.strip()
        return cleaned_value or None

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)

    @field_validator("current_password", "new_password")
    @classmethod
    def validate_bcrypt_byte_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be no more than 72 UTF-8 bytes.")
        return value


def _calculate_age(birth_date: date | None) -> int | None:
    if birth_date is None:
        return None
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _member_details_context(member_id: str, *, is_admin: bool = False):
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
                must_change_password
            FROM public.members
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="Member profile not found.")

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
        "is_admin": is_admin,
        "profile_age": _calculate_age(member.get("date_of_birth")),
    }


@router.get("/my-details", response_class=HTMLResponse)
def render_my_details_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    context = _member_details_context(current_user["member_id"], is_admin=False)
    context["request"] = request
    context["page_title"] = "My Details"
    context["page_intro"] = "Review your profile, account status, relatives, and any missing details." 
    return templates.TemplateResponse(
        request=request,
        name="member_profile_details.html",
        context=context,
    )


@router.get("/settings", response_class=HTMLResponse)
def render_profile_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="profile_settings.html",
        context={
            "request": request,
            "profile": current_user,
            "must_change_password": bool(current_user.get("must_change_password")),
            "profile_age": _calculate_age(current_user.get("date_of_birth")),
            "max_date": date.today().isoformat(),
        },
    )


@router.put("/me")
def update_member_profile(
    payload: MemberProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    try:
        with get_db() as cursor:
            cursor.execute(
                """
                UPDATE public.members
                SET phone = %s,
                    email = %s,
                    reset_token = CASE
                        WHEN LOWER(BTRIM(email)) IS DISTINCT FROM LOWER(BTRIM(%s))
                        THEN NULL ELSE reset_token
                    END,
                    reset_expires_at = CASE
                        WHEN LOWER(BTRIM(email)) IS DISTINCT FROM LOWER(BTRIM(%s))
                        THEN NULL ELSE reset_expires_at
                    END,
                    address = %s,
                    occupation = %s,
                    date_of_birth = %s,
                    next_of_kin_name = %s,
                    next_of_kin_relationship = %s,
                    next_of_kin_phone = %s
                WHERE id = %s
                RETURNING member_id, full_name, phone, email, address, occupation,
                          date_of_birth, next_of_kin_name, next_of_kin_relationship,
                          next_of_kin_phone;
                """,
                (
                    payload.phone,
                    payload.email,
                    payload.email,
                    payload.email,
                    payload.address,
                    payload.occupation,
                    payload.date_of_birth,
                    payload.next_of_kin_name,
                    payload.next_of_kin_relationship,
                    payload.next_of_kin_phone,
                    current_user["id"],
                ),
            )
            profile = cursor.fetchone()
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That phone number or email address is already associated with another account.",
        ) from exc

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member profile could not be found.",
        )

    profile["age"] = _calculate_age(profile.get("date_of_birth"))
    return {"status": "success", "message": "Profile details saved.", "profile": profile}


@router.put("/photo")
def update_member_profile_photo(
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        image_contents = image.file.read(
            home_gallery_service.MAX_IMAGE_SIZE_BYTES + 1
        )
    finally:
        image.file.close()

    try:
        uploaded_image = home_gallery_service.upload_member_profile_image(
            image_contents,
            current_user["member_id"],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except home_gallery_service.CloudinaryError as exc:
        logger.exception("Could not upload the member profile image.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    old_public_id = None
    try:
        with get_db() as cursor:
            cursor.execute(
                """
                SELECT avatar_public_id
                FROM public.members
                WHERE id = %s
                FOR UPDATE;
                """,
                (current_user["id"],),
            )
            member = cursor.fetchone()
            if member is not None:
                old_public_id = member.get("avatar_public_id")
                cursor.execute(
                    """
                    UPDATE public.members
                    SET avatar_url = %s,
                        avatar_public_id = %s
                    WHERE id = %s
                    RETURNING avatar_url;
                    """,
                    (
                        uploaded_image["image_url"],
                        uploaded_image["public_id"],
                        current_user["id"],
                    ),
                )
                saved_profile = cursor.fetchone()
            else:
                saved_profile = None
    except Exception:
        try:
            home_gallery_service.delete_cloudinary_image(uploaded_image["public_id"])
        except home_gallery_service.CloudinaryError:
            logger.exception("Could not clean up an unreferenced member profile image.")
        raise

    if saved_profile is None:
        try:
            home_gallery_service.delete_cloudinary_image(uploaded_image["public_id"])
        except home_gallery_service.CloudinaryError:
            logger.exception("Could not clean up an unreferenced member profile image.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member profile could not be found.",
        )

    old_image_warning = None
    if old_public_id and old_public_id != uploaded_image["public_id"]:
        try:
            home_gallery_service.delete_cloudinary_image(old_public_id)
        except home_gallery_service.CloudinaryError:
            logger.exception("Could not remove the replaced member profile image.")
            old_image_warning = (
                "Profile photo saved, but the previous photo could not be removed "
                "from Cloudinary."
            )

    response = {
        "status": "success",
        "message": "Profile photo updated.",
        "avatar_url": saved_profile["avatar_url"],
    }
    if old_image_warning:
        response["warning"] = old_image_warning
    return response


@router.put("/password")
def change_member_password(
    payload: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user),
):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT password_hash
            FROM public.members
            WHERE id = %s
            FOR UPDATE;
            """,
            (current_user["id"],),
        )
        account = cursor.fetchone()
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member account could not be found.",
            )

        stored_hash = account.get("password_hash")
        try:
            current_password_matches = bool(stored_hash) and bcrypt.checkpw(
                payload.current_password.encode("utf-8"),
                stored_hash.encode("utf-8")
                if isinstance(stored_hash, str)
                else stored_hash,
            )
        except (TypeError, ValueError):
            current_password_matches = False

        if not current_password_matches:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )

        if payload.current_password == payload.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose a new password different from your current password.",
            )

        password_hash = bcrypt.hashpw(
            payload.new_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
        cursor.execute(
            """
            UPDATE public.members
            SET password_hash = %s,
                must_change_password = FALSE,
                reset_token = NULL,
                reset_expires_at = NULL
            WHERE id = %s;
            """,
            (password_hash, current_user["id"]),
        )

    return {"status": "success", "message": "Password changed successfully."}
