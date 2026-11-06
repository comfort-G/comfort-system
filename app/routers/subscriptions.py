# app/routers/subscriptions.py
import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from app.dependencies import get_current_user, require_role
from app.services import home_gallery_service
from app.services import subscription_service
from fastapi import Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])

class ProofSubmissionRequest(BaseModel):
    amount: float
    proof_url: str
    notes: str = ""
    payment_method: str = "Other"
    transaction_reference: str | None = None
    cloudinary_public_id: str | None = None
    payment_month: int | None = Field(default=None, ge=1, le=12)
    payment_year: int | None = Field(default=None, ge=2000)


class ProofAllocationLine(BaseModel):
    billing_month: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class ProofReviewRequest(BaseModel):
    decision: str
    comment: str = ""
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    expected_allocations: list[ProofAllocationLine] | None = None


class ProofAllocationPreviewRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


@router.get("/view", response_class=HTMLResponse)
def render_subscriptions_page(request: Request):
    """Renders the HTML subscriptions ledger frontend page."""
    return templates.TemplateResponse(
        request=request,
        name="subscriptions.html",
        context={"request": request},
    )


# app/routers/subscriptions.py
@router.get("/ledger")
def get_my_ledger(current_user: dict = Depends(get_current_user)):
    """API endpoint for logged-in members to view their subscription ledger and summary."""
    summary = subscription_service.fetch_member_ledger_summary(current_user["member_id"])
    return {
        "status": "success",
        "data": summary
    }

@router.post("/submit-proof")
def submit_proof(
    payload: ProofSubmissionRequest, 
    current_user: dict = Depends(get_current_user)
):
    """API endpoint for members to submit payment proof."""
    try:
        response = subscription_service.submit_payment_proof(
            member_id=current_user["member_id"],
            member_name=current_user.get("full_name") or current_user["member_id"],
            amount=payload.amount,
            proof_url=payload.proof_url,
            notes=payload.notes,
            payment_method=payload.payment_method,
            transaction_reference=payload.transaction_reference,
            cloudinary_public_id=payload.cloudinary_public_id,
            payment_month=payload.payment_month,
            payment_year=payload.payment_year,
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submit-proof-upload", status_code=201)
async def submit_uploaded_proof(
    image: UploadFile = File(...),
    transaction_reference: str | None = Form(default=None, max_length=100),
    current_user: dict = Depends(get_current_user),
):
    try:
        image_contents = await image.read(
            home_gallery_service.MAX_IMAGE_SIZE_BYTES + 1
        )
    finally:
        await image.close()

    try:
        return await run_in_threadpool(
            subscription_service.submit_uploaded_payment_proof,
            member_id=current_user["member_id"],
            member_name=current_user.get("full_name") or current_user["member_id"],
            image_contents=image_contents,
            transaction_reference=transaction_reference,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except home_gallery_service.CloudinaryError as exc:
        logger.exception("Could not upload a subscription payment proof.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/admin/pending-proofs")
def get_pending_payment_proofs(
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    proofs = subscription_service.fetch_pending_payment_proofs()
    return {"status": "success", "count": len(proofs), "data": proofs}


@router.post("/admin/proofs/{proof_id}/preview")
def preview_payment_proof_allocation(
    proof_id: int,
    payload: ProofAllocationPreviewRequest,
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    try:
        return subscription_service.preview_payment_proof_allocation(
            proof_id=proof_id,
            amount=payload.amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/proofs/{proof_id}/review")
def review_payment_proof(
    proof_id: int,
    payload: ProofReviewRequest,
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    try:
        return subscription_service.review_payment_proof(
            proof_id=proof_id,
            decision=payload.decision,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            comment=payload.comment,
            amount=payload.amount,
            expected_allocations=(
                [item.model_dump() for item in payload.expected_allocations]
                if payload.expected_allocations is not None
                else None
            ),
        )
    except ValueError as exc:
        if "ledger changed since preview" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc