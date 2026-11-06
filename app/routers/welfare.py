# app/routers/welfare.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user, require_role
from app.services import welfare_service
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/api/welfare", tags=["Welfare Support"])
WELFARE_EXECUTIVE_ROLES = [
    "Chairperson",
    "Treasurer",
    "Welfare",
    "Welfare Officer",
]

class WelfareClaimPayload(BaseModel):
    support_category: str
    beneficiary_id: str
    description: str
    evidence_file_url: str = ""

class WelfareModerationPayload(BaseModel):
    status: str       # e.g., "Approved", "Rejected"
    current_stage: str # e.g., "Under Review", "Executive Approved", "Paid"
    comment: Optional[str] = ""

@router.get("/view", response_class=HTMLResponse)
def render_welfare_page(request: Request):
    """Renders the HTML welfare support dashboard frontend page."""
    return templates.TemplateResponse(
        request=request,
        name="welfare.html",
        context={"request": request},
    )
@router.get("/my-claims")
def get_my_welfare_claims(current_user: dict = Depends(get_current_user)):
    """API endpoint for members to view their welfare claims."""
    data = welfare_service.fetch_member_welfare_dashboard(current_user["member_id"])
    return {"status": "success", "data": data}


@router.get("/eligible-beneficiaries")
def get_eligible_beneficiaries(
    support_category: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        return {
            "status": "success",
            "data": welfare_service.get_eligible_beneficiaries(
                member_id=current_user["member_id"],
                member_name=current_user.get("full_name") or "Member",
                support_category=support_category,
            ),
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/claim")
def submit_claim(
    payload: WelfareClaimPayload,
    current_user: dict = Depends(get_current_user)
):
    """API endpoint for members to submit a new welfare claim."""
    try:
        response = welfare_service.submit_welfare_claim(
            member_id=current_user["member_id"],
            member_name=current_user.get("full_name") or "Member",
            support_category=payload.support_category,
            beneficiary_id=payload.beneficiary_id,
            description=payload.description,
            evidence_file_url=payload.evidence_file_url
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/admin/queue")
def get_staff_welfare_queue(
    current_user: dict = Depends(require_role(WELFARE_EXECUTIVE_ROLES))
):
    """API endpoint for staff to view the welfare queue."""
    queue = welfare_service.fetch_staff_welfare_queue()
    return {"status": "success", "count": len(queue), "data": queue}

@router.put("/admin/claims/{claim_id}/moderate")
def moderate_claim(
    claim_id: int,
    payload: WelfareModerationPayload,
    current_user: dict = Depends(require_role(WELFARE_EXECUTIVE_ROLES))
):
    """API endpoint for executives/staff to moderate a welfare claim."""
    try:
        response = welfare_service.moderate_welfare_claim(
            claim_id=claim_id,
            new_status=payload.status,
            new_stage=payload.current_stage,
            role=current_user.get("role", "Staff"),
            comment=payload.comment or "",
            actor_name=current_user.get("full_name") or current_user["member_id"],
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/claims/{claim_id}/disburse")
def disburse_claim(
    claim_id: int,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    """Records an approved welfare payment and its member-level funding ledger."""
    try:
        return welfare_service.disburse_welfare_claim(
            claim_id=claim_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", "Treasurer"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc