from decimal import Decimal, InvalidOperation

from app.repositories import executive_actions_repo

MAX_WELFARE_TRANSFER_AMOUNT = Decimal("100000")


def fetch_transferable_subscription_balances() -> list[dict]:
    return executive_actions_repo.get_transferable_subscription_balances()


def transfer_subscription_to_welfare(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
) -> dict:
    try:
        transfer_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Transfer amount must be a valid number.") from exc

    if not transfer_amount.is_finite() or transfer_amount <= 0:
        raise ValueError("Transfer amount must be greater than zero.")
    if transfer_amount.quantize(Decimal("0.01")) != transfer_amount:
        raise ValueError("Transfer amount cannot have more than two decimal places.")
    if transfer_amount > MAX_WELFARE_TRANSFER_AMOUNT:
        raise ValueError(
            f"Welfare transfer amount cannot exceed UGX {MAX_WELFARE_TRANSFER_AMOUNT:,.2f}."
        )

    result = executive_actions_repo.transfer_subscription_to_welfare(
        member_id=member_id.strip(),
        amount=transfer_amount,
        actor_name=actor_name,
        actor_role=actor_role,
    )
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    if result.get("error") == "member_on_probation":
        raise ValueError(
            "Savings cannot be transferred to welfare or applied to welfare arrears "
            "until the member completes the 60-day probation period."
        )
    if result.get("error") == "insufficient_balance":
        available = result["available"]
        raise ValueError(
            f"Transfer exceeds the available paid subscription balance "
            f"of UGX {available:,.2f}."
        )
    if result.get("error") == "welfare_limit_exceeded":
        current_total = result["current_total"]
        limit = result["limit"]
        remaining = result["remaining"]
        raise ValueError(
            f"Welfare balance is already UGX {current_total:,.2f}. "
            f"Only UGX {remaining:,.2f} remains before the maximum welfare cap of "
            f"UGX {limit:,.2f}."
        )

    transfer = result["transfer"]
    return {
        "status": "success",
        "message": (
            f"UGX {transfer_amount:,.2f} transferred to the member's welfare ledger; "
            f"UGX {result['arrears_paid']:,.2f} applied to outstanding welfare arrears."
        ),
        "transfer_id": transfer["id"],
        "transfer_reference": transfer["transfer_reference"],
        "member_id": member_id,
        "amount": float(transfer_amount),
        "arrears_paid": float(result["arrears_paid"]),
        "available_savings_balance": float(result["available_balance"]),
    }


def delete_welfare_transfer(
    transfer_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    if not reason.strip():
        raise ValueError("Enter a reason for removing the welfare transfer.")
    result = executive_actions_repo.delete_welfare_transfer(
        transfer_id=transfer_id,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=reason.strip(),
    )
    if not result:
        raise ValueError("Welfare transfer record not found.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    if result.get("error") == "automatic_transfer":
        raise ValueError(
            "Automatic welfare refills cannot be deleted from the transfer ledger."
        )
    transfer = result["transfer"]
    return {
        "status": "success",
        "message": (
            "Welfare transfer and linked arrears payments removed; the change was audited "
            f"and the member notified. Available savings are now "
            f"UGX {result['available_savings']:,.2f}."
        ),
        "transfer_id": transfer_id,
        "member_id": transfer["member_id"],
        "amount": float(transfer["amount"]),
        "arrears_paid": float(result["arrears_paid"]),
        "welfare_balance": float(result["welfare_balance"]),
        "available_savings": float(result["available_savings"]),
    }
