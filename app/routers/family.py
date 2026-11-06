from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, require_role
from app.services import family_service

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/api/family", tags=["Family Registry"])

FAMILY_EXECUTIVE_ROLES = [
    "Chairperson",
    "Treasurer",
    "Secretary",
    "Welfare",
    "Welfare Officer",
]


class FamilyRelativePayload(BaseModel):
    relationship_type: str = Field(min_length=1, max_length=100)
    full_legal_name: str = Field(min_length=1, max_length=200)
    primary_contact: str = Field(min_length=1, max_length=200)
    vital_status: str = Field(min_length=1, max_length=20)


def _actor_details(current_user: dict) -> tuple[str, str]:
    return (
        current_user.get("full_name") or current_user["member_id"],
        current_user.get("role", "Member"),
    )


def _service_error(error: Exception) -> HTTPException:
    if isinstance(error, family_service.FamilyRelativeNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.get("/view", response_class=HTMLResponse)
def render_family_page(request: Request):
    """Render the family registry page using the shared Jinja layout."""
    return templates.TemplateResponse(
        request=request,
        name="family.html",
        context={"request": request},
    )


@router.get("/relatives")
def list_family_relatives(current_user: dict = Depends(get_current_user)):
    """List the authenticated member's own family registry and submission status."""
    try:
        data = family_service.list_member_relatives(current_user["member_id"])
        data["role"] = current_user.get("role", "Member")
        return {"status": "success", "data": data}
    except ValueError as error:
        raise _service_error(error) from error


@router.post("/relatives", status_code=status.HTTP_201_CREATED)
def add_family_relative(
    payload: FamilyRelativePayload,
    current_user: dict = Depends(get_current_user),
):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.add_member_relative(
            member_id=current_user["member_id"],
            relationship_type=payload.relationship_type,
            full_legal_name=payload.full_legal_name,
            primary_contact=payload.primary_contact,
            vital_status=payload.vital_status,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    except ValueError as error:
        raise _service_error(error) from error


@router.post("/submit")
def submit_family_registry(current_user: dict = Depends(get_current_user)):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.submit_member_registry(
            current_user["member_id"], actor_name, actor_role
        )
    except ValueError as error:
        raise _service_error(error) from error


@router.put("/relatives/{relative_id}")
def update_family_relative(
    payload: FamilyRelativePayload,
    relative_id: int = Path(ge=1),
    current_user: dict = Depends(get_current_user),
):
    """Update an unsubmitted family record owned by the authenticated member."""
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.update_member_relative(
            relative_id=relative_id,
            expected_member_id=current_user["member_id"],
            relationship_type=payload.relationship_type,
            full_legal_name=payload.full_legal_name,
            primary_contact=payload.primary_contact,
            vital_status=payload.vital_status,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    except (ValueError, family_service.FamilyRelativeNotFoundError) as error:
        raise _service_error(error) from error


@router.delete("/relatives/{relative_id}")
def delete_family_relative(
    relative_id: int = Path(ge=1),
    current_user: dict = Depends(get_current_user),
):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.delete_member_relative(
            relative_id=relative_id,
            member_id=current_user["member_id"],
            actor_name=actor_name,
            actor_role=actor_role,
        )
    except (ValueError, family_service.FamilyRelativeNotFoundError) as error:
        raise _service_error(error) from error


@router.get("/executive/registries")
def list_executive_family_registries(
    _: dict = Depends(require_role(FAMILY_EXECUTIVE_ROLES)),
):
    return {
        "status": "success",
        "data": family_service.list_executive_registries(),
    }


@router.post("/executive/registries/{member_id}/relatives", status_code=status.HTTP_201_CREATED)
def add_relative_as_chairperson(
    member_id: str,
    payload: FamilyRelativePayload,
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.add_member_relative(
            member_id=member_id,
            relationship_type=payload.relationship_type,
            full_legal_name=payload.full_legal_name,
            primary_contact=payload.primary_contact,
            vital_status=payload.vital_status,
            actor_name=actor_name,
            actor_role=actor_role,
            chairperson_edit=True,
        )
    except ValueError as error:
        raise _service_error(error) from error


@router.put("/executive/relatives/{relative_id}")
def update_relative_as_chairperson(
    payload: FamilyRelativePayload,
    relative_id: int = Path(ge=1),
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.update_member_relative(
            relative_id=relative_id,
            relationship_type=payload.relationship_type,
            full_legal_name=payload.full_legal_name,
            primary_contact=payload.primary_contact,
            vital_status=payload.vital_status,
            actor_name=actor_name,
            actor_role=actor_role,
            chairperson_edit=True,
        )
    except (ValueError, family_service.FamilyRelativeNotFoundError) as error:
        raise _service_error(error) from error


@router.post("/executive/registries/{member_id}/review")
def review_family_registry(
    member_id: str,
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    actor_name, actor_role = _actor_details(current_user)
    try:
        return family_service.review_member_registry(member_id, actor_name, actor_role)
    except ValueError as error:
        raise _service_error(error) from error
