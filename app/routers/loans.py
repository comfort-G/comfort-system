# app/routers/loans.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.dependencies import get_current_user
from app.services import loan_service
from app.dependencies import require_role
from app.dependencies import get_current_user, require_role
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


router = APIRouter(prefix="/api/loans", tags=["Loans Management"])

class LoanApplicationRequest(BaseModel):
    amount: float
    purpose: str
    mobile_money_number: str = Field(min_length=9, max_length=24)

@router.get("/admin/view", response_class=RedirectResponse)
def render_loan_reviews_page(
    _: dict = Depends(require_role(["Chairperson", "Treasurer", "Secretary"])),
):
    """Keep the former loan review URL while centralizing executive actions."""
    return RedirectResponse(url="/api/executive-actions/view", status_code=307)

@router.get("/view", response_class=HTMLResponse)
def render_loans_page(request: Request):
    """Renders the HTML loans dashboard frontend page."""
    return templates.TemplateResponse(
        request=request,
        name="loans.html",
        context={"request": request},
    )

@router.get("/my-loans")
def get_my_loans(current_user: dict = Depends(get_current_user)):
    """API endpoint for logged-in members to view their loan history and active snapshot."""
    data = loan_service.fetch_member_loans(current_user["member_id"])
    return {
        "status": "success",
        "data": data
    }

@router.post("/apply")
def apply_loan(
    payload: LoanApplicationRequest,
    current_user: dict = Depends(get_current_user)
):
    """API endpoint for members to submit a new loan application."""
    try:
        response = loan_service.apply_for_loan(
            member_str_id=current_user["member_id"],
            amount=payload.amount,
            purpose=payload.purpose,
            mobile_money_number=payload.mobile_money_number,
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class LoanReviewRequest(BaseModel):
    decision: str  # "Approved" or "Rejected"
    reason: str = Field(default="", max_length=500)

@router.get("/pending-review")
def get_pending_loans(
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer", "Secretary"]))
):
    """API endpoint for executives to view all pending loan applications."""
    pending = loan_service.fetch_pending_loans_for_review()
    return {
        "status": "success",
        "count": len(pending),
        "data": pending
    }

@router.put("/{loan_id}/review")
def review_loan(
    loan_id: int,
    payload: LoanReviewRequest,
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer", "Secretary"]))
):
    """API endpoint for executives to approve or reject a loan application."""
    try:
        response = loan_service.review_loan_application(
            loan_id=loan_id,
            decision=payload.decision,
            executive_name=current_user.get("full_name", "Executive"),
            rejection_reason=payload.reason,
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))