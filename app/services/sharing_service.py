# app/services/sharing_service.py
from app.repositories import sharing_repo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math


def _as_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return amount if amount.is_finite() else Decimal("0")


def set_sharing_cycle_state(is_active: bool, executive_name: str) -> dict:
    """Allows the Chairperson to toggle year-end sharing on or off."""
    result = sharing_repo.toggle_sharing_activation_in_db(is_active)
    status_str = "activated" if is_active else "deactivated"
    return {
        "status": "success",
        "message": f"Year-end sharing has been {status_str} by Chairperson {executive_name}.",
        "cycle_state": result,
    }


def fetch_sharing_cycle_state() -> dict:
    return sharing_repo.get_sharing_activation_state() or {
        "active": False,
        "activated_on": None,
        "deactivated_on": None,
    }


def fetch_member_sharing_dashboard(member_str_id: str, current_role: str) -> dict:
    """
    Calculates the member's savings and dividends using recorded interest.
    Cleared-loan totals are used only when there are no repayment ledger entries.
    """
    state = sharing_repo.get_sharing_activation_state()
    is_unlocked = state.get("active", False) if state else False

    savings_data = sharing_repo.get_member_savings_total(member_str_id)
    remaining_savings = _as_decimal(
        savings_data.get("total_savings") if savings_data else 0
    )

    interest_pool_info = sharing_repo.get_interest_sharing_summary(member_str_id)
    member_interest_paid = _as_decimal(
        interest_pool_info.get("member_interest_paid") if interest_pool_info else 0
    )
    total_interest_pool = _as_decimal(interest_pool_info.get("total_interest_pool") if interest_pool_info else 0)
    borrower_share = _as_decimal(
        interest_pool_info.get("borrower_dividend") if interest_pool_info else 0
    )
    general_group_dividend = _as_decimal(
        interest_pool_info.get("group_dividend") if interest_pool_info else 0
    )
    total_dividends = _as_decimal(
        interest_pool_info.get("total_dividends") if interest_pool_info else 0
    )
    admin_cost_share = (total_interest_pool * Decimal("0.10")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    withdrawal_totals = sharing_repo.get_member_withdrawal_totals(member_str_id)
    disbursed_amount = _as_decimal(withdrawal_totals.get("disbursed_amount"))
    reserved_amount = _as_decimal(withdrawal_totals.get("reserved_amount"))
    total_payout = _as_decimal(
        interest_pool_info.get("available_payout") if interest_pool_info else 0
    )

    is_executive = current_role.lower() in ["chairperson", "treasurer", "secretary"]

    return {
        "member_id": member_str_id,
        "is_sharing_active": is_unlocked,
        "available_savings_payout": float(remaining_savings),
        "member_interest_paid": float(member_interest_paid),
        "borrower_interest_payout": float(borrower_share),
        "general_group_dividend": float(general_group_dividend),
        "total_dividends": float(total_dividends),
        "total_payout": float(total_payout),
        "withdrawals_pending_or_approved": float(reserved_amount),
        "withdrawals_disbursed": float(disbursed_amount),
        "withdrawal_requests": withdrawal_totals.get("requests", []),
        "admin_cost_reserve": float(admin_cost_share) if is_executive else "RESTRICTED (Executives Only)",
        "total_interest_pool": float(total_interest_pool),
        "welfare_note": "Welfare funds are locked from year-end sharing and reserved solely for welfare claims.",
    }


def process_audited_sharing_withdrawal(
    member_str_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
) -> dict:
    """Records a pending withdrawal request against the member's full payout."""
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Withdrawal amount must be greater than zero.")

    try:
        withdrawal_result = sharing_repo.create_withdrawal_if_available(
            member_str_id, Decimal(str(amount)), actor_name, actor_role
        )
    except InvalidOperation as exc:
        raise ValueError("Withdrawal amount must be a valid number.") from exc

    error = withdrawal_result.get("error")
    if error == "sharing_inactive":
        raise ValueError("Year-end sharing has not been activated by the Chairperson yet.")
    if error == "member_not_found":
        raise ValueError("Member profile not found.")
    if error == "insufficient_payout":
        available = withdrawal_result["available"]
        raise ValueError(
            f"Insufficient payout: you requested UGX {amount:,.2f}, "
            f"but only UGX {available:,.2f} is available."
        )

    return {
        "status": "pending",
        "message": "Withdrawal request submitted for Chairperson approval.",
        "request_id": withdrawal_result["withdrawal"]["id"],
        "request_status": withdrawal_result["withdrawal"]["status"],
        "amount_requested": amount,
    }


def fetch_withdrawal_queue() -> list[dict]:
    return sharing_repo.get_withdrawal_queue()


def review_withdrawal(
    withdrawal_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str = "",
) -> dict:
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("Decision must be 'approve' or 'reject'.")
    result = sharing_repo.review_withdrawal(
        withdrawal_id, normalized_decision, actor_name, actor_role, comment
    )
    if not result:
        raise ValueError("Withdrawal request not found or no longer pending.")
    decision_status = "approved" if normalized_decision == "approve" else "rejected"
    return {
        "status": "success",
        "message": f"Sharing withdrawal {decision_status}.",
        "request_id": result["id"],
        "request_status": result["status"],
    }


def disburse_withdrawal(
    withdrawal_id: int,
    actor_name: str,
    actor_role: str,
) -> dict:
    result = sharing_repo.disburse_withdrawal(
        withdrawal_id, actor_name, actor_role
    )
    if not result:
        raise ValueError("Withdrawal request not found or not approved for disbursement.")
    return {
        "status": "success",
        "message": "Sharing withdrawal marked as paid and disbursed.",
        "request_id": result["id"],
        "request_status": result["status"],
    }