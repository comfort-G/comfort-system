from datetime import date
from decimal import Decimal
from typing import Any

from app.database import get_db
from app.repositories.financial_action_lock import acquire_financial_action_lock
from app.repositories import subscription_repo


def _insert_audit(
    cursor: Any,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_name: str,
    actor_role: str,
    details: str,
    previous_value: str,
    new_value: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.audit_logs (
            entity_type, entity_id, action, actor_name, actor_role,
            details, previous_value, new_value, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW());
        """,
        (
            entity_type, entity_id, action, actor_name, actor_role,
            details, previous_value, new_value,
        ),
    )


def _insert_member_notification(
    cursor: Any,
    member_id: str,
    title: str,
    message: str,
    action_link: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.notifications (
            recipient_type, recipient_id, title, message, is_read,
            category, module_name, priority, action_link, delivery_status, created_at
        )
        VALUES (
            'Member', %s, %s, %s, FALSE, 'Finance',
            'Executive Action Center', 'Normal', %s, 'Delivered', NOW()
        );
        """,
        (member_id, title, message, action_link),
    )


def _savings_balance(cursor: Any, member_id: str) -> Decimal:
    cursor.execute(
        """
        SELECT available_savings
        FROM public.sharing_member_payouts
        WHERE member_id = %s;
        """,
        (member_id,),
    )
    row = cursor.fetchone()
    return Decimal(str(row["available_savings"] or 0)) if row else Decimal("0")


def _member_savings(cursor: Any, member_id: str) -> Decimal:
    cursor.execute(
        """
        SELECT savings
        FROM public.sharing_member_payouts
        WHERE member_id = %s;
        """,
        (member_id,),
    )
    row = cursor.fetchone()
    return Decimal(str(row["savings"] or 0)) if row else Decimal("0")


def get_member_financial_accounts() -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                member.member_id,
                member.full_name,
                COALESCE(payouts.available_savings, 0) AS available_savings
            FROM public.members AS member
            LEFT JOIN public.sharing_member_payouts AS payouts
                ON payouts.member_id = member.member_id
            ORDER BY member.full_name, member.member_id;
            """
        )
        members = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                loan_id,
                member_id,
                amount_requested,
                outstanding_balance,
                status
            FROM public.loans
            WHERE LOWER(BTRIM(COALESCE(status, ''))) IN ('approved', 'active')
              AND COALESCE(outstanding_balance, 0) > 0
            ORDER BY member_id, loan_id;
            """
        )
        loans_by_member: dict[str, list[dict]] = {}
        for loan in cursor.fetchall():
            loans_by_member.setdefault(loan["member_id"], []).append(loan)
        for member in members:
            member["loans"] = loans_by_member.get(member["member_id"], [])
        cursor.execute(
            """
            SELECT
                subscription.id,
                subscription.member_id,
                member.full_name,
                subscription.billing_month,
                subscription.amount_paid,
                subscription.status
            FROM public.subscriptions AS subscription
            JOIN public.members AS member
                ON member.member_id = subscription.member_id
            WHERE LOWER(BTRIM(COALESCE(subscription.status, ''))) = 'paid'
            ORDER BY subscription.billing_month DESC, subscription.id DESC
            """
        )
        subscriptions = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                contribution.id,
                contribution.member_id,
                member.full_name,
                contribution.amount,
                contribution.transfer_reference,
                contribution.created_by,
                contribution.created_by_role,
                contribution.created_at,
                COALESCE(arrears.amount, 0) AS arrears_paid
            FROM public.member_welfare_contributions AS contribution
            JOIN public.members AS member
                ON member.member_id = contribution.member_id
            LEFT JOIN LATERAL (
                SELECT SUM(payment.amount) AS amount
                FROM public.welfare_request_member_arrears_payments AS payment
                WHERE LEFT(
                    payment.payment_reference,
                    LENGTH(contribution.transfer_reference) + 1
                ) = contribution.transfer_reference || '-'
            ) AS arrears ON TRUE
            ORDER BY contribution.created_at DESC, contribution.id DESC;
            """
        )
        welfare_transfers = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                repayment.repayment_id,
                repayment.loan_id,
                repayment.member_id,
                member.full_name,
                repayment.principal_paid,
                repayment.interest_paid,
                repayment.recorded_by,
                repayment.recorded_at,
                repayment.is_historical
            FROM public.loan_repayments AS repayment
            LEFT JOIN public.members AS member
                ON member.member_id = repayment.member_id
            ORDER BY repayment.repayment_id DESC;
            """
        )
        loan_repayments = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                loan.loan_id,
                loan.member_id,
                member.full_name,
                loan.amount_requested,
                loan.outstanding_balance,
                loan.status,
                loan.applied_date,
                imported.source_reference,
                imported.balance_as_of_date,
                imported.imported_at,
                COUNT(repayment.repayment_id) FILTER (
                    WHERE repayment.is_historical
                ) AS historical_repayment_count,
                COUNT(repayment.repayment_id) FILTER (
                    WHERE NOT repayment.is_historical
                ) AS subsequent_repayment_count
            FROM public.historical_loan_imports imported
            JOIN public.loans loan ON loan.loan_id = imported.loan_id
            JOIN public.members member ON member.member_id = loan.member_id
            LEFT JOIN public.loan_repayments repayment
                ON repayment.loan_id = loan.loan_id
            GROUP BY
                loan.loan_id, loan.member_id, member.full_name,
                loan.amount_requested, loan.outstanding_balance, loan.status,
                loan.applied_date, imported.source_reference,
                imported.balance_as_of_date, imported.imported_at
            ORDER BY imported.imported_at DESC, loan.loan_id DESC;
            """
        )
        historical_loans = cursor.fetchall()
        return {
            "members": members,
            "subscriptions": subscriptions,
            "welfare_transfers": welfare_transfers,
            "loan_repayments": loan_repayments,
            "historical_loans": historical_loans,
        }


def import_historical_loan(
    member_id: str,
    source_reference: str,
    issued_date: date,
    balance_as_of_date: date,
    principal: Decimal,
    unpaid_interest: Decimal,
    repayments: list[dict[str, Any]],
    notes: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    principal_repaid = sum(
        (Decimal(str(item["principal_paid"])) for item in repayments),
        Decimal("0"),
    )
    interest_repaid = sum(
        (Decimal(str(item["interest_paid"])) for item in repayments),
        Decimal("0"),
    )
    principal_outstanding = principal - principal_repaid
    outstanding_balance = principal_outstanding + unpaid_interest
    status = "Paid" if outstanding_balance == 0 else "Approved"

    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT loan_id
            FROM public.historical_loan_imports
            WHERE member_id = %s
              AND voided_at IS NULL
              AND LOWER(BTRIM(source_reference)) = LOWER(BTRIM(%s))
            LIMIT 1;
            """,
            (member_id, source_reference),
        )
        if cursor.fetchone():
            return {"error": "duplicate_source_reference"}

        cursor.execute(
            """
            SELECT member_id, status
            FROM public.members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if not member:
            return {"error": "member_not_found"}
        if (member.get("status") or "").strip().casefold() == "suspended":
            return {"error": "member_account_inactive"}

        cursor.execute(
            """
            INSERT INTO public.loans (
                member_id, amount_requested, purpose, mobile_money_number,
                outstanding_balance, status, applied_date, approved_date,
                approved_at, approved_by, interest_accumulated,
                total_interest_collected, last_interest_applied_date
            )
            VALUES (
                %s, %s, %s, 'Not recorded (historical import)',
                %s, %s, %s, %s, %s::timestamp, %s, %s, %s, %s
            )
            RETURNING loan_id;
            """,
            (
                member_id,
                principal,
                notes or "Historical loan imported from local books",
                outstanding_balance,
                status,
                issued_date,
                issued_date,
                issued_date,
                actor_name,
                unpaid_interest,
                interest_repaid,
                balance_as_of_date,
            ),
        )
        loan_row = cursor.fetchone()
        if not loan_row:
            raise RuntimeError("Historical loan insert returned no confirmation.")
        loan_id = loan_row["loan_id"]

        cursor.execute(
            """
            INSERT INTO public.historical_loan_imports (
                loan_id, member_id, source_reference, balance_as_of_date,
                imported_by, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (
                loan_id,
                member_id,
                source_reference,
                balance_as_of_date,
                actor_name,
                notes,
            ),
        )

        for repayment in repayments:
            cursor.execute(
                """
                INSERT INTO public.loan_repayments (
                    loan_id, member_id, principal_paid, interest_paid,
                    recorded_by, recorded_at, is_historical
                )
                VALUES (%s, %s, %s, %s, %s, %s, TRUE);
                """,
                (
                    loan_id,
                    member_id,
                    repayment["principal_paid"],
                    repayment["interest_paid"],
                    actor_name,
                    repayment["payment_date"],
                ),
            )

        details = (
            f"Historical loan imported from local books (reference "
            f"{source_reference}). Issued {issued_date.isoformat()}; principal "
            f"UGX {principal:,.2f}; historical principal repaid "
            f"UGX {principal_repaid:,.2f}; historical interest repaid "
            f"UGX {interest_repaid:,.2f}; principal outstanding "
            f"UGX {principal_outstanding:,.2f}; unpaid interest "
            f"UGX {unpaid_interest:,.2f}; total outstanding "
            f"UGX {outstanding_balance:,.2f}; balance verified as of "
            f"{balance_as_of_date.isoformat()}; status {status}; "
            f"{len(repayments)} dated repayment(s)."
        )
        _insert_audit(
            cursor,
            "loan",
            str(loan_id),
            "historical_loan_imported",
            actor_name,
            actor_role,
            details,
            "No system loan record",
            f"{status}; outstanding UGX {outstanding_balance:,.2f}",
        )
        _insert_member_notification(
            cursor,
            member_id,
            "Historical loan added to your account",
            (
                f"Loan #{loan_id} from your historical records was added to the "
                f"system. Principal: UGX {principal:,.2f}; repaid principal: "
                f"UGX {principal_repaid:,.2f}; repaid interest: "
                f"UGX {interest_repaid:,.2f}; current outstanding: "
                f"UGX {outstanding_balance:,.2f}."
            ),
            "/api/loans/view",
        )
        return {
            "loan_id": loan_id,
            "member_id": member_id,
            "status": status,
            "principal": principal,
            "principal_repaid": principal_repaid,
            "interest_repaid": interest_repaid,
            "principal_outstanding": principal_outstanding,
            "unpaid_interest": unpaid_interest,
            "outstanding_balance": outstanding_balance,
            "repayment_count": len(repayments),
        }


def void_historical_loan_import(
    loan_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict | None:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT
                loan.loan_id,
                loan.member_id,
                loan.amount_requested,
                loan.outstanding_balance,
                loan.status,
                imported.source_reference
            FROM public.loans loan
            JOIN public.historical_loan_imports imported
                ON imported.loan_id = loan.loan_id
            WHERE loan.loan_id = %s
            FOR UPDATE OF loan, imported;
            """,
            (loan_id,),
        )
        loan = cursor.fetchone()
        if not loan:
            return {"error": "historical_import_not_found"}
        if (loan["status"] or "").strip().casefold() == "reversed":
            return {"error": "historical_import_already_voided"}

        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE NOT is_historical) AS later_repayment_count,
                COUNT(*) FILTER (WHERE is_historical) AS historical_repayment_count,
                COALESCE(SUM(principal_paid) FILTER (WHERE is_historical), 0)
                    AS principal_repaid,
                COALESCE(SUM(interest_paid) FILTER (WHERE is_historical), 0)
                    AS interest_repaid
            FROM public.loan_repayments
            WHERE loan_id = %s;
            """,
            (loan_id,),
        )
        repayment_summary = cursor.fetchone()
        if repayment_summary is None:
            raise RuntimeError("Could not verify repayments before voiding the import.")
        if repayment_summary["later_repayment_count"]:
            return {"error": "historical_import_has_later_activity"}

        cursor.execute(
            """
            DELETE FROM public.loan_repayments
            WHERE loan_id = %s AND is_historical
            RETURNING repayment_id;
            """,
            (loan_id,),
        )
        cursor.fetchall()
        cursor.execute(
            """
            UPDATE public.loans
            SET status = 'Reversed',
                outstanding_balance = 0,
                interest_accumulated = 0,
                total_interest_collected = 0
            WHERE loan_id = %s
            RETURNING loan_id;
            """,
            (loan_id,),
        )
        if not cursor.fetchone():
            raise RuntimeError("Historical loan changed before the void could be recorded.")
        cursor.execute(
            """
            UPDATE public.historical_loan_imports
            SET voided_at = clock_timestamp()::timestamp
            WHERE loan_id = %s AND voided_at IS NULL
            RETURNING loan_id;
            """,
            (loan_id,),
        )
        if not cursor.fetchone():
            raise RuntimeError("Historical import marker changed before the void was recorded.")

        previous_balance = Decimal(str(loan["outstanding_balance"] or 0))
        details = (
            f"Voided historical loan import #{loan_id} for member "
            f"{loan['member_id']} (local-book reference "
            f"{loan['source_reference']}). Removed "
            f"{repayment_summary['historical_repayment_count']} imported repayment "
            f"entry/entries: principal UGX "
            f"{Decimal(str(repayment_summary['principal_repaid'])):,.2f}; interest "
            f"UGX {Decimal(str(repayment_summary['interest_repaid'])):,.2f}. "
            f"Outstanding balance before void: UGX {previous_balance:,.2f}. "
            f"This corrects imported ledger data; it does not represent a cash "
            f"disbursement or receipt. Reason: {reason}"
        )
        _insert_audit(
            cursor,
            "loan",
            str(loan_id),
            "historical_loan_import_voided",
            actor_name,
            actor_role,
            details,
            f"{loan['status']}; outstanding UGX {previous_balance:,.2f}",
            "Reversed; no active balance",
        )
        _insert_member_notification(
            cursor,
            loan["member_id"],
            "Historical loan record corrected",
            (
                f"Historical loan #{loan_id} was voided from the system ledger "
                f"after a Treasurer correction. Reason: {reason}"
            ),
            "/api/loans/view",
        )
        return {
            "loan_id": loan_id,
            "member_id": loan["member_id"],
            "principal_repaid": Decimal(str(repayment_summary["principal_repaid"])),
            "interest_repaid": Decimal(str(repayment_summary["interest_repaid"])),
            "outstanding_balance": Decimal("0"),
        }


def record_subscription_payment(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    note: str,
    expected_allocations: list[dict[str, Any]],
) -> dict | None:
    with get_db() as cursor:
        allocations = subscription_repo.plan_subscription_allocation(
            cursor, member_id, amount, lock_member=True
        )
        if allocations is None:
            return None

        if not subscription_repo.expected_subscription_allocations_match(
            expected_allocations, allocations
        ):
            return {
                "error": "allocation_changed",
                "allocations": subscription_repo.serialize_subscription_allocations(
                    allocations
                ),
            }

        previous_balance = _savings_balance(cursor, member_id)
        subscription_ids = subscription_repo.apply_subscription_allocations(
            cursor, member_id, allocations
        )
        new_balance = _savings_balance(cursor, member_id)
        allocation_summary = ", ".join(
            f"{item['billing_month']:%B %Y}: UGX {item['amount']:,.2f}"
            for item in allocations
        )
        details = (
            f"Treasurer recorded UGX {amount:,.2f} for member {member_id}; "
            f"allocation: {allocation_summary}."
            f"{f' Note: {note}' if note else ''}"
        )
        _insert_audit(
            cursor,
            "subscription_allocation",
            member_id,
            "treasurer_subscription_allocation_recorded",
            actor_name,
            actor_role,
            details,
            str(previous_balance),
            str(new_balance),
        )
        _insert_member_notification(
            cursor,
            member_id,
            "Subscription payment recorded",
            (
                f"UGX {amount:,.2f} was allocated across {allocation_summary}. "
                f"Your available savings are now "
                f"UGX {new_balance:,.2f}."
            ),
            "/api/subscriptions/view",
        )
        return {
            "subscription_ids": subscription_ids,
            "allocations": allocations,
            "previous_balance": previous_balance,
            "available_balance": new_balance,
        }


def delete_subscription_payment(
    subscription_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT member_id
            FROM public.subscriptions
            WHERE id = %s
            ;
            """,
            (subscription_id,),
        )
        initial = cursor.fetchone()
        if not initial:
            return None

        cursor.execute(
            "SELECT member_id FROM public.members WHERE member_id = %s FOR UPDATE;",
            (initial["member_id"],),
        )
        if not cursor.fetchone():
            return {"error": "member_not_found"}

        cursor.execute(
            """
            SELECT id, member_id, billing_month, amount_paid, status
            FROM public.subscriptions
            WHERE id = %s
            FOR UPDATE;
            """,
            (subscription_id,),
        )
        subscription = cursor.fetchone()
        if not subscription:
            return None
        if (subscription.get("status") or "").strip().casefold() != "paid":
            return {"error": "not_paid"}

        previous_balance = _savings_balance(cursor, subscription["member_id"])
        cursor.execute(
            "DELETE FROM public.subscriptions WHERE id = %s RETURNING id;",
            (subscription_id,),
        )
        if not cursor.fetchone():
            return None
        new_balance = _savings_balance(cursor, subscription["member_id"])
        amount = Decimal(str(subscription["amount_paid"] or 0))
        details = (
            f"Deleted paid subscription {subscription_id} for "
            f"member {subscription['member_id']}, "
            f"{subscription['billing_month']:%B %Y} (UGX {amount:,.2f}). "
            f"Reason: {reason}"
        )
        _insert_audit(
            cursor,
            "subscription",
            str(subscription_id),
            "treasurer_subscription_deleted",
            actor_name,
            actor_role,
            details,
            str(previous_balance),
            str(new_balance),
        )
        _insert_member_notification(
            cursor,
            subscription["member_id"],
            "Subscription payment corrected",
            (
                f"A paid subscription of UGX {amount:,.2f} for "
                f"{subscription['billing_month']:%B %Y} was removed from your account. "
                f"Your available savings are now UGX {new_balance:,.2f}. "
                f"Reason: {reason}"
            ),
            "/api/subscriptions/view",
        )
        return {
            "subscription": subscription,
            "previous_balance": previous_balance,
            "available_balance": new_balance,
        }


def record_loan_installment(
    loan_id: int,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    note: str,
) -> dict | None:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT
                loan_id, member_id, amount_requested, outstanding_balance, status
            FROM public.loans
            WHERE loan_id = %s
            FOR UPDATE;
            """,
            (loan_id,),
        )
        loan = cursor.fetchone()
        if not loan:
            return None
        if (loan.get("status") or "").strip().casefold() not in {"approved", "active"}:
            return {"error": "loan_not_active"}

        outstanding = Decimal(str(loan["outstanding_balance"] or 0))
        if amount > outstanding:
            return {"error": "overpayment", "outstanding": outstanding}

        cursor.execute(
            """
            SELECT COALESCE(SUM(principal_paid), 0) AS principal_paid,
                   COALESCE(SUM(interest_paid), 0) AS interest_paid
            FROM public.loan_repayments
            WHERE loan_id = %s;
            """,
            (loan_id,),
        )
        repayment_totals = cursor.fetchone()
        principal_remaining = max(
            Decimal(str(loan["amount_requested"] or 0))
            - Decimal(str(repayment_totals["principal_paid"] or 0)),
            Decimal("0"),
        )
        interest_outstanding = max(outstanding - principal_remaining, Decimal("0"))
        interest_paid = min(amount, interest_outstanding)
        principal_paid = amount - interest_paid
        new_outstanding = outstanding - amount
        new_interest_accumulated = max(
            interest_outstanding - interest_paid,
            Decimal("0"),
        )

        cursor.execute(
            """
            INSERT INTO public.loan_repayments (
                loan_id, member_id, principal_paid, interest_paid,
                recorded_by, recorded_at, is_historical
            )
            VALUES (%s, %s, %s, %s, %s, clock_timestamp()::timestamp, FALSE);
            """,
            (
                loan_id,
                loan["member_id"],
                principal_paid,
                interest_paid,
                actor_name,
            ),
        )
        cursor.execute(
            """
            UPDATE public.loans
            SET outstanding_balance = %s,
                interest_accumulated = %s,
                total_interest_collected = COALESCE(total_interest_collected, 0) + %s,
                status = CASE WHEN %s = 0 THEN 'Paid' ELSE status END
            WHERE loan_id = %s;
            """,
            (
                new_outstanding,
                new_interest_accumulated,
                interest_paid,
                new_outstanding,
                loan_id,
            ),
        )
        details = (
            f"Recorded loan installment UGX {amount:,.2f} for loan {loan_id}: "
            f"UGX {interest_paid:,.2f} interest and UGX {principal_paid:,.2f} principal."
            f" Member: {loan['member_id']}."
            f"{f' Note: {note}' if note else ''}"
        )
        _insert_audit(
            cursor,
            "loan_repayment",
            str(loan_id),
            "treasurer_loan_installment_recorded",
            actor_name,
            actor_role,
            details,
            str(outstanding),
            str(new_outstanding),
        )
        _insert_member_notification(
            cursor,
            loan["member_id"],
            "Loan installment recorded",
            (
                f"UGX {amount:,.2f} was recorded for loan {loan_id} "
                f"(UGX {interest_paid:,.2f} interest; UGX {principal_paid:,.2f} principal). "
                f"Remaining loan balance: UGX {new_outstanding:,.2f}."
            ),
            "/api/loans/view",
        )
        return {
            "loan_id": loan_id,
            "member_id": loan["member_id"],
            "amount": amount,
            "interest_paid": interest_paid,
            "principal_paid": principal_paid,
            "outstanding_balance": new_outstanding,
        }


def delete_loan_installment(
    repayment_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict | None:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT loan_id, member_id, outstanding_balance,
                   amount_requested, total_interest_collected, status
            FROM public.loans
            WHERE loan_id = (
                SELECT loan_id
                FROM public.loan_repayments
                WHERE repayment_id = %s
            )
            FOR UPDATE;
            """,
            (repayment_id,),
        )
        loan = cursor.fetchone()
        if not loan:
            return None

        cursor.execute(
            """
            SELECT repayment_id, loan_id, member_id, principal_paid, interest_paid
            FROM public.loan_repayments
            WHERE repayment_id = %s AND loan_id = %s
            FOR UPDATE;
            """,
            (repayment_id, loan["loan_id"]),
        )
        repayment = cursor.fetchone()
        if not repayment:
            return None
        if repayment["member_id"] != loan["member_id"]:
            return {"error": "member_mismatch"}

        principal_paid = Decimal(str(repayment["principal_paid"] or 0))
        interest_paid = Decimal(str(repayment["interest_paid"] or 0))
        amount = principal_paid + interest_paid
        if amount <= 0:
            return {"error": "invalid_repayment"}
        previous_balance = Decimal(str(loan["outstanding_balance"] or 0))
        new_balance = previous_balance + amount
        previous_interest = Decimal(str(loan["total_interest_collected"] or 0))
        new_interest = max(previous_interest - interest_paid, Decimal("0"))

        cursor.execute(
            """
            DELETE FROM public.loan_repayments
            WHERE repayment_id = %s
            RETURNING repayment_id;
            """,
            (repayment_id,),
        )
        if not cursor.fetchone():
            return None
        cursor.execute(
            """
            SELECT COALESCE(SUM(principal_paid), 0) AS principal_paid
            FROM public.loan_repayments
            WHERE loan_id = %s;
            """,
            (loan["loan_id"],),
        )
        remaining_repayments = cursor.fetchone()
        if remaining_repayments is None:
            raise RuntimeError("Could not recalculate loan principal after repayment removal.")
        principal_remaining = max(
            Decimal(str(loan["amount_requested"] or 0))
            - Decimal(str(remaining_repayments["principal_paid"] or 0)),
            Decimal("0"),
        )
        new_interest_accumulated = max(
            new_balance - principal_remaining,
            Decimal("0"),
        )
        cursor.execute(
            """
            UPDATE public.loans
            SET outstanding_balance = %s,
                interest_accumulated = %s,
                total_interest_collected = %s,
                status = CASE
                    WHEN LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                         AND %s > 0 THEN 'Approved'
                    ELSE status
                END
            WHERE loan_id = %s;
            """,
            (
                new_balance,
                new_interest_accumulated,
                new_interest,
                new_balance,
                loan["loan_id"],
            ),
        )
        details = (
            f"Removed loan repayment {repayment_id} for loan {loan['loan_id']} "
            f"(member {repayment['member_id']}): UGX {amount:,.2f} "
            f"(UGX {interest_paid:,.2f} interest; UGX {principal_paid:,.2f} principal). "
            f"Reason: {reason}"
        )
        _insert_audit(
            cursor,
            "loan_repayment",
            str(repayment_id),
            "treasurer_loan_installment_deleted",
            actor_name,
            actor_role,
            details,
            str(previous_balance),
            str(new_balance),
        )
        _insert_member_notification(
            cursor,
            repayment["member_id"],
            "Loan installment corrected",
            (
                f"A loan installment of UGX {amount:,.2f} was removed from loan "
                f"{loan['loan_id']}. Updated outstanding balance: "
                f"UGX {new_balance:,.2f}. Reason: {reason}"
            ),
            "/api/loans/view",
        )
        return {
            "loan_id": loan["loan_id"],
            "member_id": repayment["member_id"],
            "amount": amount,
            "outstanding_balance": new_balance,
            "total_interest_collected": new_interest,
        }


def create_savings_withdrawal_request(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT member_id, full_name
            FROM public.members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if not member:
            return {"error": "member_not_found"}

        previous_balance = _savings_balance(cursor, member_id)
        if amount > previous_balance:
            return {"error": "insufficient_balance", "available": previous_balance}

        cursor.execute(
            """
            INSERT INTO public.treasurer_savings_withdrawals (
                member_id, amount, reason, status, requested_by, requested_role
            )
            VALUES (%s, %s, %s, 'Pending', %s, %s)
            RETURNING id, member_id, amount, reason, status, requested_on;
            """,
            (member_id, amount, reason, actor_name, actor_role),
        )
        withdrawal = cursor.fetchone()
        new_balance = _savings_balance(cursor, member_id)
        _insert_audit(
            cursor,
            "treasurer_savings_withdrawal",
            str(withdrawal["id"]),
            "treasurer_savings_withdrawal_requested",
            actor_name,
            actor_role,
            (
                f"Requested withdrawal of UGX {amount:,.2f} from member {member_id}; "
                f"awaiting Chairperson approval. Reason: {reason}"
            ),
            str(previous_balance),
            str(new_balance),
        )
        _insert_member_notification(
            cursor,
            member_id,
            "Savings withdrawal awaiting approval",
            (
                f"A withdrawal of UGX {amount:,.2f} was requested from your savings. "
                f"It will only be deducted after Chairperson approval. Reason: {reason}"
            ),
            "/api/sharing/view",
        )
        cursor.execute(
            """
            SELECT member_id
            FROM public.members
            WHERE LOWER(BTRIM(COALESCE(role, ''))) = 'chairperson';
            """
        )
        for chair in cursor.fetchall():
            cursor.execute(
                """
                INSERT INTO public.notifications (
                    recipient_type, recipient_id, title, message, is_read,
                    category, module_name, priority, action_link, delivery_status, created_at
                )
                VALUES (
                    'Member', %s, 'Savings withdrawal requires approval', %s, FALSE,
                    'Finance', 'Executive Action Center', 'High',
                    '/api/executive-actions/view', 'Delivered', NOW()
                );
                """,
                (
                    chair["member_id"],
                    (
                        f"{member.get('full_name') or member_id} ({member_id}) has a "
                        f"UGX {amount:,.2f} savings withdrawal awaiting your review."
                    ),
                ),
            )
        return {
            "withdrawal": withdrawal,
            "previous_balance": previous_balance,
            "available_balance": new_balance,
        }


def get_pending_savings_withdrawals() -> list[dict]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                withdrawal.id,
                withdrawal.member_id,
                member.full_name,
                withdrawal.amount,
                withdrawal.reason,
                withdrawal.status,
                withdrawal.requested_by,
                withdrawal.requested_on,
                COALESCE(payouts.available_savings, 0) AS available_savings
            FROM public.treasurer_savings_withdrawals AS withdrawal
            JOIN public.members AS member ON member.member_id = withdrawal.member_id
            LEFT JOIN public.sharing_member_payouts AS payouts
                ON payouts.member_id = withdrawal.member_id
            WHERE LOWER(BTRIM(withdrawal.status)) = 'pending'
            ORDER BY withdrawal.requested_on, withdrawal.id;
            """
        )
        return cursor.fetchall()


def review_savings_withdrawal(
    withdrawal_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str,
) -> dict | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, member_id, amount, reason, status
            FROM public.treasurer_savings_withdrawals
            WHERE id = %s
            FOR UPDATE;
            """,
            (withdrawal_id,),
        )
        withdrawal = cursor.fetchone()
        if not withdrawal or withdrawal["status"].strip().casefold() != "pending":
            return None

        cursor.execute(
            "SELECT member_id FROM public.members WHERE member_id = %s FOR UPDATE;",
            (withdrawal["member_id"],),
        )
        if not cursor.fetchone():
            return {"error": "member_not_found"}

        previous_balance = _savings_balance(cursor, withdrawal["member_id"])
        previous_savings = _member_savings(cursor, withdrawal["member_id"])
        amount = Decimal(str(withdrawal["amount"]))
        if decision == "approve":
            cursor.execute(
                """
                SELECT
                    GREATEST(
                        payouts.remaining_savings
                        - LEAST(
                            payouts.remaining_savings,
                            GREATEST(
                                payouts.reserved_amount
                                - GREATEST(
                                    payouts.total_dividends - payouts.disbursed_amount,
                                    0
                                ),
                                0
                            )
                        )
                        - COALESCE(other_pending.amount, 0),
                        0
                    ) AS available_without_this_request
                FROM public.sharing_member_payouts AS payouts
                LEFT JOIN (
                    SELECT member_id, SUM(amount) AS amount
                    FROM public.treasurer_savings_withdrawals
                    WHERE LOWER(BTRIM(status)) = 'pending'
                      AND id <> %s
                    GROUP BY member_id
                ) AS other_pending ON other_pending.member_id = payouts.member_id
                WHERE payouts.member_id = %s;
                """,
                (withdrawal_id, withdrawal["member_id"]),
            )
            available_row = cursor.fetchone()
            available_without_this_request = Decimal(
                str(available_row["available_without_this_request"] or 0)
            ) if available_row else Decimal("0")
            if amount > available_without_this_request:
                return {
                    "error": "insufficient_balance",
                    "available": available_without_this_request,
                }

        status = "Approved" if decision == "approve" else "Rejected"
        cursor.execute(
            """
            UPDATE public.treasurer_savings_withdrawals
            SET status = %s, reviewed_by = %s, reviewed_role = %s,
                reviewed_on = NOW(), review_comment = %s
            WHERE id = %s AND LOWER(BTRIM(status)) = 'pending'
            RETURNING id, member_id, amount, reason, status;
            """,
            (status, actor_name, actor_role, comment, withdrawal_id),
        )
        reviewed = cursor.fetchone()
        if not reviewed:
            return None

        new_balance = _savings_balance(cursor, withdrawal["member_id"])
        new_savings = _member_savings(cursor, withdrawal["member_id"])
        _insert_audit(
            cursor,
            "treasurer_savings_withdrawal",
            str(withdrawal_id),
            (
                "treasurer_savings_withdrawal_approved"
                if decision == "approve"
                else "treasurer_savings_withdrawal_rejected"
            ),
            actor_name,
            actor_role,
            (
                f"Chairperson {decision} withdrawal of UGX {amount:,.2f} from member "
                f"{withdrawal['member_id']}. Reason: {withdrawal['reason']}. "
                f"{f'Review note: {comment}' if comment else ''}"
            ),
            str(previous_savings),
            str(new_savings),
        )
        balance_message = (
            f" Your available savings are now UGX {new_balance:,.2f}."
            if decision == "approve"
            else f" Your available savings are now UGX {new_balance:,.2f}; no funds were deducted."
        )
        _insert_member_notification(
            cursor,
            withdrawal["member_id"],
            f"Savings withdrawal {status.casefold()}",
            (
                f"Your requested withdrawal of UGX {amount:,.2f} was {status.casefold()} "
                f"by the Chairperson.{balance_message}"
                + (f" Review note: {comment}" if comment else "")
            ),
            "/api/sharing/view",
        )
        return {
            "withdrawal": reviewed,
            "previous_balance": previous_balance,
            "available_balance": new_balance,
        }
