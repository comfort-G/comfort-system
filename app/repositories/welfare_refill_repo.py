from decimal import Decimal
from uuid import uuid4
from typing import Any

from app.database import get_db

WELFARE_ACCOUNT_MAX = Decimal("100000.00")
_REFILL_BATCH_SIZE = 100


def _allocate_refill_credit(
    cursor: Any,
    member_id: str,
    amount: Decimal,
    due_only: bool,
) -> list[str]:
    due_filter = "AND contributions.auto_refill_due_at <= NOW()" if due_only else ""
    cursor.execute(
        f"""
        SELECT
            contributions.id,
            contributions.request_id,
            requests.case_number,
            contributions.welfare_amount,
            contributions.auto_refilled_amount
        FROM public.welfare_request_member_contributions AS contributions
        JOIN public.welfare_requests AS requests
            ON requests.id = contributions.request_id
        WHERE contributions.member_id = %s
          AND contributions.auto_refill_due_at IS NOT NULL
          AND contributions.auto_refilled_amount < contributions.welfare_amount
          {due_filter}
        ORDER BY contributions.auto_refill_due_at, contributions.id
        FOR UPDATE OF contributions;
        """,
        (member_id,),
    )
    remaining = amount
    case_numbers = []
    for row in cursor.fetchall():
        if remaining <= 0:
            break
        refill_remaining = (
            Decimal(str(row["welfare_amount"]))
            - Decimal(str(row["auto_refilled_amount"]))
        )
        allocated = min(remaining, refill_remaining)
        cursor.execute(
            """
            UPDATE public.welfare_request_member_contributions
            SET auto_refilled_amount = auto_refilled_amount + %s
            WHERE id = %s;
            """,
            (allocated, row["id"]),
        )
        remaining -= allocated
        case_numbers.append(row["case_number"])
    return list(dict.fromkeys(case_numbers))


def _transfer_to_welfare(
    cursor: Any,
    member_id: str,
    due_only: bool,
) -> dict | None:
    cursor.execute(
        """
        SELECT
            COALESCE(balances.welfare_balance, 0) AS welfare_balance,
            COALESCE(payouts.available_savings, 0) AS savings_balance
        FROM public.members AS members
        LEFT JOIN public.member_welfare_balances AS balances
            ON balances.member_id = members.member_id
        LEFT JOIN public.sharing_member_payouts AS payouts
            ON payouts.member_id = members.member_id
        WHERE members.member_id = %s
        FOR UPDATE OF members;
        """,
        (member_id,),
    )
    balances = cursor.fetchone()
    if not balances:
        return None

    welfare_balance = Decimal(str(balances["welfare_balance"] or 0))
    savings_balance = Decimal(str(balances["savings_balance"] or 0))
    remaining_capacity = max(WELFARE_ACCOUNT_MAX - welfare_balance, Decimal("0"))
    due_amount = None
    if due_only:
        cursor.execute(
            """
            SELECT COALESCE(
                SUM(welfare_amount - auto_refilled_amount), 0
            ) AS due_amount
            FROM public.welfare_request_member_contributions
            WHERE member_id = %s
              AND auto_refill_due_at <= NOW()
              AND auto_refilled_amount < welfare_amount;
            """,
            (member_id,),
        )
        due_amount = Decimal(str(cursor.fetchone()["due_amount"] or 0))

    amount = min(remaining_capacity, savings_balance)
    if due_amount is not None:
        amount = min(amount, due_amount)
    if amount <= 0:
        return None

    transfer_reference = f"WEL-AUTO-{uuid4().hex[:12].upper()}"
    cursor.execute(
        """
        INSERT INTO public.member_welfare_contributions (
            member_id, amount, transfer_reference, created_by, created_by_role
        )
        VALUES (%s, %s, %s, 'Automatic welfare refill', 'System')
        RETURNING id, created_at;
        """,
        (member_id, amount, transfer_reference),
    )
    transfer = cursor.fetchone()
    case_numbers = _allocate_refill_credit(
        cursor,
        member_id,
        amount,
        due_only=due_only,
    )

    cursor.execute(
        """
        SELECT COALESCE(available_savings, 0) AS available_savings
        FROM public.sharing_member_payouts
        WHERE member_id = %s;
        """,
        (member_id,),
    )
    savings_row = cursor.fetchone()
    new_savings_balance = Decimal(
        str(savings_row["available_savings"] or 0) if savings_row else 0
    )
    new_welfare_balance = welfare_balance + amount
    if case_numbers:
        reason = (
            "to replenish the welfare contribution for case(s) "
            f"{', '.join(case_numbers)}"
        )
    elif due_only:
        reason = "to replenish welfare deductions that reached their 24-hour due time"
    else:
        reason = "to build the welfare balance toward its UGX 100,000 maximum"

    cursor.execute(
        """
        INSERT INTO public.audit_logs (
            entity_type, entity_id, action, actor_name, actor_role, details,
            previous_value, new_value, created_at
        )
        VALUES (
            'member_welfare_contribution', %s, 'automatic_savings_to_welfare_refill',
            'System', 'System', %s, %s, %s, NOW()
        );
        """,
        (
            str(transfer["id"]),
            (
                f"Automatically moved UGX {amount:,.2f} from member {member_id}'s "
                f"savings to welfare {reason}. Welfare balance changed from "
                f"UGX {welfare_balance:,.2f} to UGX {new_welfare_balance:,.2f}."
            ),
            str(balances["savings_balance"]),
            str(new_savings_balance),
        ),
    )
    cursor.execute(
        """
        INSERT INTO public.notifications (
            recipient_type, recipient_id, title, message, is_read, category,
            module_name, priority, action_link, delivery_status, created_at
        )
        VALUES (
            'Member', %s, 'Automatic welfare account refill', %s, FALSE,
            'Welfare', 'Welfare Support', 'Normal', '/api/welfare/view',
            'Delivered', NOW()
        );
        """,
        (
            member_id,
            (
                f"UGX {amount:,.2f} was automatically transferred from your savings "
                f"to your welfare account {reason}. Your welfare balance is now "
                f"UGX {new_welfare_balance:,.2f} (maximum UGX "
                f"{WELFARE_ACCOUNT_MAX:,.2f}); your available savings are now "
                f"UGX {new_savings_balance:,.2f}."
            ),
        ),
    )
    return {
        "member_id": member_id,
        "amount": amount,
        "welfare_balance": new_welfare_balance,
        "available_savings": new_savings_balance,
        "case_numbers": case_numbers,
    }


def top_up_welfare_from_savings(cursor: Any, member_id: str) -> dict | None:
    """Immediately moves available savings into welfare, up to the account cap."""
    return _transfer_to_welfare(cursor, member_id, due_only=False)


def top_up_existing_welfare_balances() -> dict:
    """Top up existing member accounts that have available savings and room."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT members.member_id
            FROM public.members AS members
            LEFT JOIN public.member_welfare_balances AS balances
                ON balances.member_id = members.member_id
            LEFT JOIN public.sharing_member_payouts AS payouts
                ON payouts.member_id = members.member_id
            WHERE COALESCE(balances.welfare_balance, 0) < %s
              AND COALESCE(payouts.available_savings, 0) > 0
            ORDER BY members.member_id
            LIMIT %s
            FOR UPDATE OF members SKIP LOCKED;
            """,
            (WELFARE_ACCOUNT_MAX, _REFILL_BATCH_SIZE),
        )
        refills = [
            result
            for member in cursor.fetchall()
            if (
                result := _transfer_to_welfare(
                    cursor,
                    member["member_id"],
                    due_only=False,
                )
            )
        ]
    return {
        "member_count": len(refills),
        "transfer_count": len(refills),
        "amount": sum((refill["amount"] for refill in refills), Decimal("0")),
        "has_more": len(refills) == _REFILL_BATCH_SIZE,
    }


def process_due_welfare_refills() -> dict:
    """Refills welfare deductions at least 24 hours old when savings are available."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT members.member_id
            FROM public.members AS members
            WHERE EXISTS (
                SELECT 1
                FROM public.welfare_request_member_contributions AS contributions
                WHERE contributions.member_id = members.member_id
                  AND contributions.auto_refill_due_at <= NOW()
                  AND contributions.auto_refilled_amount
                      < contributions.welfare_amount
            )
            ORDER BY members.member_id
            LIMIT %s
            FOR UPDATE OF members SKIP LOCKED;
            """,
            (_REFILL_BATCH_SIZE,),
        )
        refills = [
            result
            for member in cursor.fetchall()
            if (
                result := _transfer_to_welfare(
                    cursor,
                    member["member_id"],
                    due_only=True,
                )
            )
        ]
    return {
        "member_count": len(refills),
        "transfer_count": len(refills),
        "amount": sum((refill["amount"] for refill in refills), Decimal("0")),
    }
