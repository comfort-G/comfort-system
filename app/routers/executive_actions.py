from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.dependencies import require_role
from app.services import (
    emergency_reversal_service,
    executive_actions_service,
    member_finance_actions_service,
)
from app.subscription_rules import MONTHLY_SUBSCRIPTION_TARGET


EXECUTIVE_ROLES = [
    "Chairperson",
    "Treasurer",
    "Secretary",
    "Welfare",
    "Welfare Officer",
]
templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/api/executive-actions", tags=["Executive Action Center"])


class SubscriptionTransferRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SubscriptionAllocationLine(BaseModel):
    billing_month: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class ManualSubscriptionRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    note: str = Field(default="", max_length=500)
    expected_allocations: list[SubscriptionAllocationLine] = Field(min_length=1)


class SubscriptionPreviewRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SubscriptionDeletionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class FinanceCorrectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class LoanInstallmentRequest(BaseModel):
    loan_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    note: str = Field(default="", max_length=500)


class HistoricalLoanRepaymentLine(BaseModel):
    payment_date: date
    principal_paid: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    interest_paid: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)


class HistoricalLoanImportRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    source_reference: str = Field(min_length=3, max_length=120)
    issued_date: date
    balance_as_of_date: date
    principal: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    unpaid_interest: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    repayments: list[HistoricalLoanRepaymentLine] = Field(default_factory=list, max_length=500)
    notes: str = Field(default="", max_length=500)


class HistoricalLoanVoidRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


class SavingsWithdrawalRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=1, max_length=500)


class SavingsWithdrawalReviewRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=20)
    comment: str = Field(default="", max_length=500)


class EmergencyReversalRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)
    funds_received: bool


@router.get("/view", response_class=HTMLResponse)
def render_executive_actions_page(
    request: Request,
    current_user: dict = Depends(require_role(EXECUTIVE_ROLES)),
):
    role = (current_user.get("role") or "").strip().casefold()
    return templates.TemplateResponse(
        request=request,
        name="executive_actions.html",
        context={
            "request": request,
            "can_review_proofs": role in {"chairperson", "treasurer"},
            "can_review_loans": role in {"chairperson", "treasurer", "secretary"},
            "can_moderate_welfare": role in {
                "chairperson", "treasurer", "welfare", "welfare officer"
            },
            "welfare_role": role,
            "can_transfer_subscriptions": role == "treasurer",
            "can_publish_announcements": role in {"chairperson", "secretary"},
            "can_manage_home_gallery": role in {"chairperson", "secretary"},
            "can_toggle_sharing": role == "chairperson",
            "can_approve_sharing": role == "chairperson",
            "can_disburse_sharing": role == "treasurer",
            "can_manage_member_finances": role == "treasurer",
            "can_emergency_reverse": role in {"chairperson", "treasurer"},
            "monthly_subscription_target": MONTHLY_SUBSCRIPTION_TARGET,
            "can_review_member_withdrawals": role == "chairperson",
            "can_manage_members": role in {"chairperson", "treasurer", "secretary"},
            "can_override_members": role == "chairperson",
            "can_manage_member_accounts": role in {"chairperson", "secretary"},
        },
    )


@router.get("/emergency-reversal/latest")
def get_latest_emergency_reversal_action(
    _current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    return {
        "status": "success",
        "data": emergency_reversal_service.fetch_latest_emergency_action(),
    }


@router.post("/emergency-reversal/{action_type}/{action_id}")
def reverse_latest_financial_action(
    action_type: str,
    action_id: int,
    payload: EmergencyReversalRequest,
    current_user: dict = Depends(require_role(["Chairperson", "Treasurer"])),
):
    try:
        return emergency_reversal_service.reverse_latest_action(
            action_type=action_type,
            action_id=action_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
            funds_received=payload.funds_received,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/member-finances")
def get_member_financial_accounts(
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    return {
        "status": "success",
        "data": member_finance_actions_service.get_member_financial_accounts(),
    }


@router.post("/historical-loans")
def import_historical_loan(
    payload: HistoricalLoanImportRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.import_historical_loan(
            member_id=payload.member_id,
            source_reference=payload.source_reference,
            issued_date=payload.issued_date,
            balance_as_of_date=payload.balance_as_of_date,
            principal=payload.principal,
            unpaid_interest=payload.unpaid_interest,
            repayments=[
                repayment.model_dump() for repayment in payload.repayments
            ],
            notes=payload.notes,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
        )
    except ValueError as exc:
        status_code = (
            409
            if "already been imported" in str(exc)
            else 400
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/historical-loans/{loan_id}")
def void_historical_loan_import(
    loan_id: int,
    payload: HistoricalLoanVoidRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.void_historical_loan_import(
            loan_id=loan_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
        )
    except ValueError as exc:
        if "not found" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if "system repayment" in str(exc) or "already been voided" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/member-subscriptions")
def record_member_subscription(
    payload: ManualSubscriptionRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.record_subscription_payment(
            member_id=payload.member_id,
            amount=payload.amount,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            note=payload.note,
            expected_allocations=[
                item.model_dump() for item in payload.expected_allocations
            ],
        )
    except ValueError as exc:
        if str(exc) == "allocation_changed":
            raise HTTPException(
                status_code=409,
                detail="The member ledger changed since preview. Preview the allocation again.",
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/member-subscriptions/preview")
def preview_member_subscription(
    payload: SubscriptionPreviewRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.preview_subscription_payment(
            member_id=payload.member_id,
            amount=payload.amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/member-subscriptions/{subscription_id}")
def delete_member_subscription(
    subscription_id: int,
    payload: SubscriptionDeletionRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.delete_subscription_payment(
            subscription_id=subscription_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/member-welfare-transfers/{transfer_id}")
def delete_member_welfare_transfer(
    transfer_id: int,
    payload: FinanceCorrectionRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return executive_actions_service.delete_welfare_transfer(
            transfer_id=transfer_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/loan-installments")
def record_member_loan_installment(
    payload: LoanInstallmentRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.record_loan_installment(
            loan_id=payload.loan_id,
            amount=payload.amount,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/loan-installments/{repayment_id}")
def delete_member_loan_installment(
    repayment_id: int,
    payload: FinanceCorrectionRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.delete_loan_installment(
            repayment_id=repayment_id,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/member-withdrawals")
def request_member_savings_withdrawal(
    payload: SavingsWithdrawalRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return member_finance_actions_service.create_savings_withdrawal_request(
            member_id=payload.member_id,
            amount=payload.amount,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/member-withdrawals")
def get_member_savings_withdrawal_queue(
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    return {
        "status": "success",
        "data": member_finance_actions_service.get_pending_savings_withdrawals(),
    }


@router.put("/member-withdrawals/{withdrawal_id}/review")
def review_member_savings_withdrawal(
    withdrawal_id: int,
    payload: SavingsWithdrawalReviewRequest,
    current_user: dict = Depends(require_role(["Chairperson"])),
):
    try:
        return member_finance_actions_service.review_savings_withdrawal(
            withdrawal_id=withdrawal_id,
            decision=payload.decision,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/subscription-balances")
def get_transferable_subscription_balances(
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    return {
        "status": "success",
        "data": executive_actions_service.fetch_transferable_subscription_balances(),
    }


@router.post("/subscription-transfers")
def transfer_subscription_to_welfare(
    payload: SubscriptionTransferRequest,
    current_user: dict = Depends(require_role(["Treasurer"])),
):
    try:
        return executive_actions_service.transfer_subscription_to_welfare(
            member_id=payload.member_id,
            amount=payload.amount,
            actor_name=current_user.get("full_name") or current_user["member_id"],
            actor_role=current_user.get("role", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
