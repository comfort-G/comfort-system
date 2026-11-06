# app/services/subscription_service.py
from datetime import date
from decimal import Decimal
import logging
import math

from app.repositories import subscription_repo
from app.services import home_gallery_service
from app.subscription_rules import (
    MONTHLY_SUBSCRIPTION_TARGET,
    calculate_subscription_arrears,
)

logger = logging.getLogger(__name__)


def fetch_member_ledger_summary(member_str_id: str) -> dict:
    """
    Gathers the member's monthly subscription history and paid totals.
    """
    ledger = subscription_repo.get_subscriptions_by_member_str(member_str_id)
    records = ledger["history"]
    total_paid = float(ledger["total_paid_contributions"] or 0)
    current_year_paid = float(
        ledger["current_year_paid_contributions"] or 0
    )
    today = date.today()
    arrears, expected_contributions = calculate_subscription_arrears(
        current_year_paid, today
    )
    months_due = today.month
    pending_count = sum(
        1
        for record in records
        if (record.get("status") or "").strip().casefold() == "pending"
    )

    return {
        "member_id": member_str_id,
        "total_paid_contributions": total_paid,
        "current_savings": float(ledger["current_savings"] or 0),
        "current_year_paid_contributions": current_year_paid,
        "monthly_subscription_target": MONTHLY_SUBSCRIPTION_TARGET,
        "months_due": months_due,
        "expected_contributions": expected_contributions,
        "subscription_arrears": arrears,
        "arrears_period": f"January through {today.strftime('%B')} {today.year}",
        "pending_proofs_count": pending_count,
        "history": records
    }

def submit_payment_proof(
    member_id: str,
    member_name: str,
    amount: float,
    proof_url: str,
    notes: str,
    payment_method: str,
    transaction_reference: str | None,
    cloudinary_public_id: str | None,
    payment_month: int | None,
    payment_year: int | None,
) -> dict:
    """
    Business logic: Validates subscription payment details before saving.
    """
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Subscription amount must be greater than zero.")
    if not proof_url.strip():
        raise ValueError("Payment proof URL is required.")
    if not payment_method.strip():
        raise ValueError("Payment method is required.")

    month = payment_month or date.today().month
    year = payment_year or date.today().year
    if month < 1 or month > 12:
        raise ValueError("Payment month must be between 1 and 12.")
    if year < 2000 or year > date.today().year + 1:
        raise ValueError("Payment year is invalid.")

    result = subscription_repo.insert_payment_proof(
        member_id=member_id,
        member_name=member_name,
        amount=amount,
        proof_url=proof_url.strip(),
        notes=notes.strip(),
        payment_method=payment_method.strip(),
        transaction_reference=transaction_reference,
        cloudinary_public_id=(cloudinary_public_id or proof_url).strip(),
        payment_month=month,
        payment_year=year,
    )
    return {
        "status": "success",
        "message": "Payment proof submitted successfully for treasurer review.",
        "proof_id": result["proof_id"],
    }


def submit_uploaded_payment_proof(
    member_id: str,
    member_name: str,
    image_contents: bytes,
    transaction_reference: str | None = None,
) -> dict:
    uploaded_image = home_gallery_service.upload_subscription_payment_proof(
        image_contents
    )
    try:
        return submit_payment_proof(
            member_id=member_id,
            member_name=member_name,
            amount=MONTHLY_SUBSCRIPTION_TARGET,
            proof_url=uploaded_image["image_url"],
            notes="MTN MoMo transaction SMS screenshot submitted for review.",
            payment_method="MTN MoMo",
            transaction_reference=transaction_reference,
            cloudinary_public_id=uploaded_image["public_id"],
            payment_month=date.today().month,
            payment_year=date.today().year,
        )
    except Exception:
        try:
            home_gallery_service.delete_cloudinary_image(
                uploaded_image["public_id"]
            )
        except home_gallery_service.CloudinaryError:
            logger.exception(
                "Could not remove an unreferenced subscription payment proof."
            )
        raise


def fetch_pending_payment_proofs() -> list[dict]:
    return subscription_repo.get_pending_subscription_proofs()


def preview_payment_proof_allocation(
    proof_id: int,
    amount: Decimal,
) -> dict:
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Enter the transaction amount shown in the proof.")
    if amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("Transaction amount cannot have more than two decimals.")
    result = subscription_repo.preview_subscription_proof_allocation(
        proof_id, amount
    )
    if not result:
        raise ValueError("Payment proof not found.")
    if result.get("error") == "already_reviewed":
        raise ValueError("Payment proof has already been reviewed.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile for this payment proof was not found.")
    return {
        "status": "success",
        "proof_id": proof_id,
        "member_id": result["member_id"],
        "amount": str(amount),
        "allocations": result["allocations"],
    }


def review_payment_proof(
    proof_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str,
    amount: Decimal | None = None,
    expected_allocations: list[dict] | None = None,
) -> dict:
    normalized_decision = decision.strip().casefold()
    if normalized_decision not in {"paid", "rejected"}:
        raise ValueError("Decision must be Paid or Rejected.")
    if normalized_decision == "paid":
        if amount is None or not amount.is_finite() or amount <= 0:
            raise ValueError("Enter the verified transaction amount before approval.")
        if amount.quantize(Decimal("0.01")) != amount:
            raise ValueError("Transaction amount cannot have more than two decimals.")
        if not expected_allocations:
            raise ValueError("Preview the allocation before confirming the payment.")
    decision_title = normalized_decision.title()
    result = subscription_repo.review_subscription_payment_proof(
        proof_id=proof_id,
        decision=decision_title,
        actor_name=actor_name,
        actor_role=actor_role,
        comment=comment.strip(),
        amount=amount,
        expected_allocations=expected_allocations,
    )
    if not result:
        raise ValueError("Payment proof not found.")
    if result.get("error") == "already_reviewed":
        raise ValueError("Payment proof has already been reviewed.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile for this payment proof was not found.")
    if result.get("error") == "invalid_amount":
        raise ValueError("Enter the verified transaction amount before approval.")
    if result.get("error") == "preview_required":
        raise ValueError("Preview the allocation before confirming the payment.")
    if result.get("error") == "allocation_changed":
        raise ValueError(
            "The member ledger changed since preview. Preview the allocation again."
        )
    return {
        "status": "success",
        "message": (
            "Payment proof approved, allocated to monthly dues, and added to the ledger."
            if decision_title == "Paid"
            else "Payment proof rejected."
        ),
        **result,
    }