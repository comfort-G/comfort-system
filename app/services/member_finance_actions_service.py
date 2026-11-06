from datetime import date
from decimal import Decimal, InvalidOperation

from app.repositories import member_finance_actions_repo
from app.repositories import loan_repo
from app.repositories import subscription_repo


def _validated_amount(value: Decimal) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Amount must be a valid number.") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    if amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("Amount cannot have more than two decimal places.")
    return amount


def get_member_financial_accounts() -> dict:
    return member_finance_actions_repo.get_member_financial_accounts()


def import_historical_loan(
    member_id: str,
    source_reference: str,
    issued_date: date,
    balance_as_of_date: date,
    principal: Decimal,
    unpaid_interest: Decimal,
    repayments: list[dict],
    notes: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    member_id = member_id.strip()
    if not member_id:
        raise ValueError("Select the member who received this loan.")

    source_reference = source_reference.strip()
    if len(source_reference) < 3:
        raise ValueError(
            "Enter a unique source reference, such as a ledger page or receipt number."
        )
    if issued_date > balance_as_of_date:
        raise ValueError("The balance date cannot be earlier than the loan issue date.")
    if balance_as_of_date > date.today():
        raise ValueError("The balance date cannot be in the future.")

    principal = _validated_amount(principal)
    unpaid_interest = Decimal(str(unpaid_interest))
    if (
        not unpaid_interest.is_finite()
        or unpaid_interest < 0
        or unpaid_interest.quantize(Decimal("0.01")) != unpaid_interest
    ):
        raise ValueError(
            "Unpaid interest must be zero or a valid amount with at most two decimal places."
        )
    if principal + unpaid_interest > Decimal("9999999999.99"):
        raise ValueError("The loan balance exceeds the supported ledger amount.")

    normalized_repayments = []
    principal_repaid = Decimal("0")
    interest_repaid = Decimal("0")
    for index, repayment in enumerate(repayments, start=1):
        payment_date = repayment["payment_date"]
        principal_paid = Decimal(str(repayment["principal_paid"]))
        interest_paid = Decimal(str(repayment["interest_paid"]))
        for label, amount in (
            ("principal", principal_paid),
            ("interest", interest_paid),
        ):
            if (
                not amount.is_finite()
                or amount < 0
                or amount.quantize(Decimal("0.01")) != amount
            ):
                raise ValueError(
                    f"Repayment {index}: {label} must be zero or a valid "
                    "amount with at most two decimal places."
                )
        if principal_paid + interest_paid <= 0:
            raise ValueError(
                f"Repayment {index}: enter a principal or interest amount greater than zero."
            )
        if payment_date < issued_date or payment_date > balance_as_of_date:
            raise ValueError(
                f"Repayment {index}: its date must be between the issue date "
                "and the balance date."
            )
        principal_repaid += principal_paid
        interest_repaid += interest_paid
        normalized_repayments.append({
            "payment_date": payment_date,
            "principal_paid": principal_paid,
            "interest_paid": interest_paid,
        })

    if principal_repaid > principal:
        raise ValueError(
            "Historical principal repayments exceed the original principal."
        )
    if interest_repaid > Decimal("9999999999.99"):
        raise ValueError("Historical interest exceeds the supported ledger amount.")
    normalized_repayments.sort(key=lambda repayment: repayment["payment_date"])

    result = member_finance_actions_repo.import_historical_loan(
        member_id=member_id,
        source_reference=source_reference,
        issued_date=issued_date,
        balance_as_of_date=balance_as_of_date,
        principal=principal,
        unpaid_interest=unpaid_interest,
        repayments=normalized_repayments,
        notes=notes.strip(),
        actor_name=actor_name,
        actor_role=actor_role,
    )
    if result.get("error") == "member_not_found":
        raise ValueError("The selected member profile could not be found.")
    if result.get("error") == "member_account_inactive":
        raise ValueError("A suspended member's account cannot receive financial entries.")
    if result.get("error") == "duplicate_source_reference":
        raise ValueError(
            "That local-book reference has already been imported. "
            "Check the existing loan ledger before trying again."
        )
    return {
        "status": "success",
        "message": (
            "Historical loan and dated repayments were added to the ledgers. "
            "Balances and audit records were updated."
        ),
        **{
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in result.items()
        },
    }


def void_historical_loan_import(
    loan_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise ValueError("Provide a correction reason of at least 8 characters.")
    result = member_finance_actions_repo.void_historical_loan_import(
        loan_id=loan_id,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=normalized_reason,
    )
    if not result:
        raise ValueError("Historical loan import not found.")
    if result.get("error") == "historical_import_not_found":
        raise ValueError("Historical loan import not found.")
    if result.get("error") == "historical_import_already_voided":
        raise ValueError("This historical loan import has already been voided.")
    if result.get("error") == "historical_import_has_later_activity":
        raise ValueError(
            "This loan has a system repayment recorded after import. Correct or "
            "remove that later repayment before voiding the historical entry."
        )
    return {
        "status": "success",
        "message": (
            "Historical loan import voided, imported repayments removed from "
            "interest and principal totals, and the correction audited."
        ),
        **{
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in result.items()
        },
    }


def preview_subscription_payment(
    member_id: str,
    amount: Decimal,
) -> dict:
    amount = _validated_amount(amount)
    if not member_id.strip():
        raise ValueError("Select a member.")
    preview = subscription_repo.preview_member_subscription_allocation(
        member_id.strip(), amount
    )
    if preview is None:
        raise ValueError("Member profile not found.")
    return {
        "status": "success",
        "amount": str(amount),
        "allocations": preview["allocations"],
    }


def record_subscription_payment(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    note: str,
    expected_allocations: list[dict],
) -> dict:
    amount = _validated_amount(amount)
    if not member_id.strip():
        raise ValueError("Select a member.")
    if not expected_allocations:
        raise ValueError("Preview the allocation before confirming the payment.")
    result = member_finance_actions_repo.record_subscription_payment(
        member_id=member_id.strip(),
        amount=amount,
        actor_name=actor_name,
        actor_role=actor_role,
        note=note.strip(),
        expected_allocations=expected_allocations,
    )
    if not result:
        raise ValueError("Member profile not found.")
    if result.get("error") == "allocation_changed":
        raise ValueError("allocation_changed")
    return {
        "status": "success",
        "message": "Subscription payment allocated and added to member savings.",
        "subscription_ids": result["subscription_ids"],
        "member_id": member_id,
        "amount": float(amount),
        "allocations": subscription_repo.serialize_subscription_allocations(
            result["allocations"]
        ),
        "available_savings": float(result["available_balance"]),
    }


def delete_subscription_payment(
    subscription_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    if not reason.strip():
        raise ValueError("Enter a reason for removing the subscription.")
    result = member_finance_actions_repo.delete_subscription_payment(
        subscription_id=subscription_id,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=reason.strip(),
    )
    if not result:
        raise ValueError("Subscription record not found.")
    if result.get("error") == "not_paid":
        raise ValueError("Only a paid subscription can be removed here.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    subscription = result["subscription"]
    return {
        "status": "success",
        "message": "Subscription removed, audited, and member savings updated.",
        "subscription_id": subscription_id,
        "member_id": subscription["member_id"],
        "available_savings": float(result["available_balance"]),
    }


def record_loan_installment(
    loan_id: int,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    note: str,
) -> dict:
    amount = _validated_amount(amount)
    loan_repo.apply_due_loan_interest()
    result = member_finance_actions_repo.record_loan_installment(
        loan_id=loan_id,
        amount=amount,
        actor_name=actor_name,
        actor_role=actor_role,
        note=note.strip(),
    )
    if not result:
        raise ValueError("Loan not found.")
    if result.get("error") == "loan_not_active":
        raise ValueError("Installments can only be recorded for an active loan.")
    if result.get("error") == "overpayment":
        raise ValueError(
            f"Installment exceeds the outstanding loan balance of "
            f"UGX {result['outstanding']:,.2f}."
        )
    return {
        "status": "success",
        "message": "Loan installment recorded and loan balance updated.",
        "loan_id": loan_id,
        "member_id": result["member_id"],
        "amount": float(amount),
        "interest_paid": float(result["interest_paid"]),
        "principal_paid": float(result["principal_paid"]),
        "outstanding_balance": float(result["outstanding_balance"]),
    }


def delete_loan_installment(
    repayment_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    if not reason.strip():
        raise ValueError("Enter a reason for removing the loan installment.")
    result = member_finance_actions_repo.delete_loan_installment(
        repayment_id=repayment_id,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=reason.strip(),
    )
    if not result:
        raise ValueError("Loan installment record not found.")
    if result.get("error") == "member_mismatch":
        raise ValueError(
            "The repayment member does not match the loan member; no changes were made."
        )
    if result.get("error") == "invalid_repayment":
        raise ValueError(
            "This repayment has an invalid amount and cannot be reversed safely."
        )
    return {
        "status": "success",
        "message": "Loan installment removed, loan balance recalculated, and the change audited.",
        "repayment_id": repayment_id,
        "loan_id": result["loan_id"],
        "member_id": result["member_id"],
        "amount": float(result["amount"]),
        "outstanding_balance": float(result["outstanding_balance"]),
    }


def create_savings_withdrawal_request(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    amount = _validated_amount(amount)
    if not member_id.strip():
        raise ValueError("Select a member.")
    if not reason.strip():
        raise ValueError("Enter a reason for the withdrawal.")
    result = member_finance_actions_repo.create_savings_withdrawal_request(
        member_id=member_id.strip(),
        amount=amount,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=reason.strip(),
    )
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    if result.get("error") == "insufficient_balance":
        raise ValueError(
            f"Withdrawal exceeds available savings of "
            f"UGX {result['available']:,.2f}."
        )
    withdrawal = result["withdrawal"]
    return {
        "status": "pending",
        "message": "Withdrawal submitted for Chairperson approval.",
        "withdrawal_id": withdrawal["id"],
        "member_id": member_id,
        "amount": float(amount),
        "available_savings": float(result["available_balance"]),
    }


def get_pending_savings_withdrawals() -> list[dict]:
    return member_finance_actions_repo.get_pending_savings_withdrawals()


def review_savings_withdrawal(
    withdrawal_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str,
) -> dict:
    normalized_decision = decision.strip().casefold()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("Decision must be Approve or Reject.")
    if normalized_decision == "reject" and not comment.strip():
        raise ValueError("Enter a reason when rejecting a withdrawal.")

    result = member_finance_actions_repo.review_savings_withdrawal(
        withdrawal_id=withdrawal_id,
        decision=normalized_decision,
        actor_name=actor_name,
        actor_role=actor_role,
        comment=comment.strip(),
    )
    if not result:
        raise ValueError("Withdrawal not found or it has already been reviewed.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    if result.get("error") == "insufficient_balance":
        raise ValueError(
            "The member's available savings changed and no longer cover this request."
        )
    decision_status = "approved" if normalized_decision == "approve" else "rejected"
    return {
        "status": "success",
        "message": f"Withdrawal {decision_status}.",
        "withdrawal_id": withdrawal_id,
        "member_id": result["withdrawal"]["member_id"],
        "available_savings": float(result["available_balance"]),
    }
