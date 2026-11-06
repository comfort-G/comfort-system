import json
import logging
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.dependencies import get_current_user, require_role
from app.services import home_gallery_service


router = APIRouter(prefix="/api/about", tags=["About Us"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
PROFILE_PATH = Path(__file__).resolve().parents[1] / "data" / "executive_team.json"
LOANS_COMMITTEE_PROFILE_PATH = Path(__file__).resolve().parents[1] / "data" / "loans_committee.json"
PROFILE_LOCK = Lock()

EXECUTIVE_OFFICES = (
    {
        "key": "chairperson",
        "office": "Chairperson",
        "responsibilities": "Leads the group, chairs meetings, and provides oversight for committee decisions.",
    },
    {
        "key": "vice_chairperson",
        "office": "Vice Chairperson",
        "responsibilities": "Supports the Chairperson and provides leadership continuity when delegated.",
    },
    {
        "key": "treasurer",
        "office": "Treasurer",
        "responsibilities": "Keeps financial records and reports on authorized group funds and transactions.",
    },
    {
        "key": "secretary",
        "office": "Secretary",
        "responsibilities": "Maintains meeting minutes, official correspondence, and group records.",
    },
    {
        "key": "vice_secretary",
        "office": "Vice Secretary",
        "responsibilities": "Assists the Secretary with meeting records, communication, and administrative duties.",
    },
    {
        "key": "publicity",
        "office": "Publicity",
        "responsibilities": "Coordinates approved group communications, notices, and public information.",
    },
    {
        "key": "welfare",
        "office": "Welfare",
        "responsibilities": "Coordinates member welfare requests and helps communicate support decisions.",
    },
    {
        "key": "chief_mobilizer",
        "office": "Chief Mobilizer",
        "responsibilities": "Encourages member participation and coordinates group mobilization activities.",
    },
    {
        "key": "assistant_mobilizer",
        "office": "Assistant Mobilizer",
        "responsibilities": "Supports the Chief Mobilizer with member engagement and group activities.",
    },
)
LOANS_COMMITTEE_OFFICES = (
    {
        "key": "loans_officer",
        "office": "Loans Officer",
        "responsibilities": "Heads the Loans Committee.",
    },
    {
        "key": "loans_member_1",
        "office": "Member",
        "responsibilities": "Serves on the Loans Committee.",
    },
    {
        "key": "loans_member_2",
        "office": "Loans Secretary",
        "responsibilities": "Maintains the Loans Committee's records and supports its lending work.",
    },
)
PROFILE_EDIT_ROLES = ["Chairperson", "Secretary"]
MAX_PROFILE_IMAGE_SIZE_BYTES = home_gallery_service.MAX_IMAGE_SIZE_BYTES


class ExecutiveProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="", max_length=120)
    photo_url: str = Field(default="", max_length=2048)
    photo_public_id: str = Field(default="", max_length=255)

    @field_validator("photo_url")
    @classmethod
    def require_secure_cloudinary_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "res.cloudinary.com"
            or not parsed.path
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Photo URL must be a secure Cloudinary image URL.")
        return value


def _read_profiles(
    profile_path: Path,
    offices: tuple[dict[str, str], ...],
    team_name: str,
) -> dict[str, dict[str, str]]:
    try:
        with profile_path.open(encoding="utf-8") as profile_file:
            profiles = json.load(profile_file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Could not read %s profiles from %s.", team_name, profile_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not load {team_name} profiles.",
        ) from exc

    if not isinstance(profiles, dict):
        logger.error("%s profile data must be a JSON object.", team_name.title())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{team_name.title()} profile data is invalid.",
        )

    validated_profiles = {}
    allowed_keys = {office["key"] for office in offices}
    for office_key, profile in profiles.items():
        if team_name == "executive" and office_key == "welfare_officer":
            continue
        if office_key not in allowed_keys or not isinstance(profile, dict):
            logger.error("%s profile data contains an invalid office entry.", team_name.title())
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{team_name.title()} profile data is invalid.",
            )
        try:
            validated_profile = ExecutiveProfile.model_validate(profile)
        except ValidationError as exc:
            logger.exception("%s profile data contains invalid profile details.", team_name.title())
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{team_name.title()} profile data is invalid.",
            ) from exc
        validated_profiles[office_key] = validated_profile.model_dump()
    return validated_profiles


def _save_profiles(
    profiles: dict[str, dict[str, str]],
    profile_path: Path,
    team_name: str,
) -> None:
    temporary_path = None
    try:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=profile_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(profiles, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, profile_path)
    except OSError as exc:
        logger.exception("Could not save %s profiles to %s.", team_name, profile_path)
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove temporary %s profile data.", team_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save {team_name} profiles.",
        ) from exc


def _get_team_profiles(
    profile_path: Path,
    offices: tuple[dict[str, str], ...],
    team_name: str,
) -> list[dict[str, str]]:
    profiles = _read_profiles(profile_path, offices, team_name)
    return [
        {
            **office,
            "name": profiles.get(office["key"], {}).get("name", ""),
            "photo_url": profiles.get(office["key"], {}).get("photo_url", ""),
            "photo_public_id": profiles.get(office["key"], {}).get("photo_public_id", ""),
        }
        for office in offices
    ]


def _update_team_profile(
    office_key: str,
    name: str,
    image: UploadFile | None,
    profile_path: Path,
    offices: tuple[dict[str, str], ...],
    team_name: str,
    image_uploader: Callable[[bytes, str], dict[str, str]],
) -> dict[str, str]:
    if office_key not in {office["key"] for office in offices}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{team_name.title()} office not found.",
        )

    image_contents = None
    if image is not None:
        try:
            image_contents = image.file.read(MAX_PROFILE_IMAGE_SIZE_BYTES + 1)
        finally:
            image.file.close()
        if not image_contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select a profile image or remove the empty file selection.",
            )
        if len(image_contents) > MAX_PROFILE_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile images must be 5 MB or smaller.",
            )

    if len(name.strip()) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Officer name cannot exceed 120 characters.",
        )

    uploaded_image = None
    if image_contents is not None:
        try:
            uploaded_image = image_uploader(image_contents, office_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except home_gallery_service.CloudinaryError as exc:
            logger.exception("Could not upload the %s profile image.", team_name)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    old_public_id = None
    try:
        with PROFILE_LOCK:
            profiles = _read_profiles(profile_path, offices, team_name)
            old_profile = profiles.get(office_key, {})
            old_public_id = old_profile.get("photo_public_id")
            profile = {
                "name": name.strip(),
                "photo_url": old_profile.get("photo_url", ""),
                "photo_public_id": old_public_id or "",
            }
            if uploaded_image:
                profile["photo_url"] = uploaded_image["image_url"]
                profile["photo_public_id"] = uploaded_image["public_id"]
            profiles[office_key] = profile
            _save_profiles(profiles, profile_path, team_name)
    except Exception:
        if uploaded_image:
            try:
                home_gallery_service.delete_cloudinary_image(uploaded_image["public_id"])
            except home_gallery_service.CloudinaryError:
                logger.exception("Could not clean up an unreferenced %s image.", team_name)
        raise

    old_image_warning = None
    if uploaded_image and old_public_id and old_public_id != uploaded_image["public_id"]:
        try:
            home_gallery_service.delete_cloudinary_image(old_public_id)
        except home_gallery_service.CloudinaryError:
            logger.exception("Could not remove the replaced %s profile image.", team_name)
            old_image_warning = (
                f"Profile saved, but the previous photo could not be removed from Cloudinary."
            )

    response = {
        "status": "success",
        "message": f"{team_name.title()} profile updated.",
        "office_key": office_key,
    }
    if old_image_warning:
        response["warning"] = old_image_warning
    return response


@router.get("/page", response_class=HTMLResponse)
def render_about_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> HTMLResponse:
    role = (current_user.get("role") or "").strip().casefold()
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={
            "request": request,
            "executive_team": _get_team_profiles(
                PROFILE_PATH, EXECUTIVE_OFFICES, "executive"
            ),
            "loans_committee": _get_team_profiles(
                LOANS_COMMITTEE_PROFILE_PATH, LOANS_COMMITTEE_OFFICES, "loans committee"
            ),
            "can_edit_executive_team": role in {"chairperson", "secretary"},
        },
    )


@router.put("/executive-team/{office_key}")
def update_executive_profile(
    office_key: str,
    name: str = Form(default="", max_length=120),
    image: UploadFile | None = File(default=None),
    current_user: dict = Depends(require_role(PROFILE_EDIT_ROLES)),
) -> dict:
    return _update_team_profile(
        office_key,
        name,
        image,
        PROFILE_PATH,
        EXECUTIVE_OFFICES,
        "executive",
        home_gallery_service.upload_executive_profile_image,
    )


@router.put("/loans-committee/{office_key}")
def update_loans_committee_profile(
    office_key: str,
    name: str = Form(default="", max_length=120),
    image: UploadFile | None = File(default=None),
    current_user: dict = Depends(require_role(PROFILE_EDIT_ROLES)),
) -> dict:
    return _update_team_profile(
        office_key,
        name,
        image,
        LOANS_COMMITTEE_PROFILE_PATH,
        LOANS_COMMITTEE_OFFICES,
        "loans committee",
        home_gallery_service.upload_loans_committee_profile_image,
    )
