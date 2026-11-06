# app/routers/sharing.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user, require_role
from app.services import sharing_service
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from decimal import Decimal
from pydantic import Field

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/api/sharing", tags=["Sharing & Dividends"])

class CycleActivationPayload(BaseModel):
    is_active: bool  # True to unlock year-end sharing, False to lock it

class AuditedWithdrawalPayload(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class WithdrawalReviewPayload(BaseModel):
    decision: str
    comment: str = Field(default="", max_length=1000)


@router.get("/view", response_class=HTMLResponse)
def render_sharing_page(request: Request):
    """Renders the HTML frontend sharing dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="sharing.html",
        context={"request": request},
    )

@router.get("/dashboard")
def get_sharing_dashboard(current_user: dict = Depends(get_current_user)):
    """
    API endpoint for members to view their savings share and interest dividends.
    Restricts the 10% admin cost reserve view strictly to Chairperson, Treasurer, and Secretary.
    """
    data = sharing_service.fetch_member_sharing_dashboard(
        member_str_id=current_user["member_id"],
        current_role=current_user.get("role", "")
    )
    return {
        "status": "success",
        "data": data
    }

@router.post("/withdraw")
def request_sharing_withdrawal(
    payload: AuditedWithdrawalPayload,
    current_user: dict = Depends(get_current_user)
):
    """
    API endpoint for members to withdraw their available savings during year-end sharing.
    Fails if the Chairperson has not yet activated the sharing cycle.
    """
    try:
        response = sharing_service.process_audited_sharing_withdrawal(
            member_str_id=current_user["member_id"],
            amount=payload.amount,
            actor_name=current_user.get("full_name", "Member"),
            actor_role=current_user.get("role", "Member"),
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/withdrawals")
def get_withdrawal_queue(
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    return {
        "status": "success",
        "data": sharing_service.fetch_withdrawal_queue(),
    }


@router.put("/admin/withdrawals/{withdrawal_id}/review")
def review_withdrawal(
    withdrawal_id: int,
    payload: WithdrawalReviewPayload,
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    try:
        return sharing_service.review_withdrawal(
            withdrawal_id=withdrawal_id,
            decision=payload.decision,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/withdrawals/{withdrawal_id}/disburse")
def disburse_withdrawal(
    withdrawal_id: int,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return sharing_service.disburse_withdrawal(
            withdrawal_id=withdrawal_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/cycle-toggle")
def toggle_sharing_cycle(
    payload: CycleActivationPayload,
    current_user: dict = Depends(require_role(["Chairperson"]))  # STRICTLY CHAIRPERSON ONLY
):
    """
    API endpoint allowing ONLY the Chairperson to activate or deactivate the year-end sharing cycle.
    """
    try:
        response = sharing_service.set_sharing_cycle_state(
            is_active=payload.is_active,
            executive_name=current_user.get("full_name", "Chairperson")
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/cycle")
def get_admin_sharing_cycle(
    current_user: dict = Depends(
        require_role(["Chairperson", "Treasurer", "Secretary", "Welfare", "Welfare Officer"])
    ),
):
    return {
        "status": "success",
        "data": sharing_service.fetch_sharing_cycle_state(),
    }