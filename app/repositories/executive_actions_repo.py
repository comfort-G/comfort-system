from decimal import Decimal
from uuid import uuid4

from app.database import get_db
from app.membership_rules import is_probationary_member
from app.repositories.financial_action_lock import acquire_financial_action_lock


def get_transferable_subscription_balances() -> list[dict]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                m.member_id,
                m.full_name,
                COALESCE(m.joined_date, m.join_date, CURRENT_DATE) AS joined_date,
                COALESCE(payouts.available_savings, 0) AS available_balance
            FROM members m
            JOIN public.sharing_member_payouts payouts
                ON payouts.member_id = m.member_id
            WHERE payouts.available_savings > 0
            ORDER BY m.full_name, m.member_id;
            """
        )
        return [
            {
                "member_id": member["member_id"],
                "full_name": member["full_name"],
                "available_balance": member["available_balance"],
            }
            for member in cursor.fetchall()
            if not is_probationary_member(member["joined_date"])
        ]


def transfer_subscription_to_welfare(
    member_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
) -> dict:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT
                member_id,
                COALESCE(joined_date, join_date, CURRENT_DATE) AS joined_date
            FROM public.members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if not member:
            return {"error": "member_not_found"}
        if is_probationary_member(member["joined_date"]):
            return {"error": "member_on_probation"}

        cursor.execute(
            """
            SELECT available_savings
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        savings_row = cursor.fetchone()
        available_balance = Decimal(
            str(savings_row["available_savings"] if savings_row else 0)
        )

        cursor.execute(
            """
            SELECT welfare_balance AS current_welfare_balance
            FROM public.member_welfare_balances
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        current_welfare_balance = Decimal(
            str(cursor.fetchone()["current_welfare_balance"])
        )
        if amount > available_balance:
            return {"error": "insufficient_balance", "available": available_balance}

        welfare_limit = Decimal("100000")
        cursor.execute(
            """
            SELECT
                contributions.request_id,
                requests.case_number,
                GREATEST(
                    contributions.outstanding_amount
                        - COALESCE(SUM(payments.amount), 0),
                    0
                ) AS amount_due
            FROM public.welfare_request_member_contributions contributions
            JOIN public.welfare_requests requests
                ON requests.id = contributions.request_id
            LEFT JOIN public.welfare_request_member_arrears_payments payments
                ON payments.request_id = contributions.request_id
               AND payments.member_id = contributions.member_id
            WHERE contributions.member_id = %s
            GROUP BY contributions.request_id, requests.case_number,
                     contributions.outstanding_amount, requests.created_at
            HAVING contributions.outstanding_amount
                - COALESCE(SUM(payments.amount), 0) > 0
            ORDER BY requests.created_at, contributions.request_id;
            """,
            (member_id,),
        )
        arrears = cursor.fetchall()
        arrears_total = sum(
            (Decimal(str(row["amount_due"])) for row in arrears),
            Decimal("0"),
        )
        arrears_payment = min(amount, arrears_total)
        amount_added_to_balance = amount - arrears_payment
        if current_welfare_balance + amount_added_to_balance > welfare_limit:
            return {
                "error": "welfare_limit_exceeded",
                "current_total": current_welfare_balance,
                "limit": welfare_limit,
                "remaining": max(
                    welfare_limit - current_welfare_balance,
                    Decimal("0"),
                ) + arrears_payment,
            }

        transfer_reference = f"WEL-SUB-{uuid4().hex[:12].upper()}"
        cursor.execute(
            """
            INSERT INTO public.member_welfare_contributions (
                member_id, amount, transfer_reference, created_by, created_by_role
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, member_id, amount, transfer_reference, created_at;
            """,
            (member_id, amount, transfer_reference, actor_name, actor_role),
        )
        transfer = cursor.fetchone()
        remaining_arrears_payment = arrears_payment
        for arrear in arrears:
            if remaining_arrears_payment <= 0:
                break
            amount_for_request = min(
                remaining_arrears_payment,
                Decimal(str(arrear["amount_due"])),
            )
            cursor.execute(
                """
                INSERT INTO public.welfare_request_member_arrears_payments (
                    request_id, member_id, amount, payment_reference,
                    created_by, created_by_role, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp()::timestamp);
                """,
                (
                    arrear["request_id"],
                    member_id,
                    amount_for_request,
                    f"{transfer_reference}-{arrear['request_id']}",
                    actor_name,
                    actor_role,
                ),
            )
            remaining_arrears_payment -= amount_for_request

        cursor.execute(
            """
            INSERT INTO public.notifications (
                recipient_type, recipient_id, title, message, is_read,
                category, module_name, priority, action_link, delivery_status, created_at
            )
            VALUES (
                'Member', %s, 'Welfare contribution recorded', %s, FALSE,
                'Welfare', 'Welfare Support', 'Normal', '/api/welfare/view',
                'Delivered', NOW()
            );
            """,
            (
                member_id,
                (
                    f"UGX {amount:,.2f} was transferred to the welfare ledger. "
                    f"UGX {arrears_payment:,.2f} cleared prior welfare arrears; "
                    f"UGX {amount_added_to_balance:,.2f} remains in your welfare balance."
                ),
            ),
        )
        remaining_balance = available_balance - amount
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'member_welfare_contribution', %s, 'savings_to_welfare_transfer',
                %s, %s, %s, %s, %s, NOW()
            );
            """,
            (
                str(transfer["id"]),
                actor_name,
                actor_role,
                (
                    f"Transferred UGX {amount:,.2f} from available savings to welfare; "
                    f"UGX {arrears_payment:,.2f} applied to arrears."
                ),
                str(available_balance),
                str(remaining_balance),
            ),
        )
        return {
            "transfer": transfer,
            "available_balance": remaining_balance,
            "arrears_paid": arrears_payment,
        }


def delete_welfare_transfer(
    transfer_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
) -> dict | None:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT member_id
            FROM public.member_welfare_contributions
            WHERE id = %s;
            """,
            (transfer_id,),
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
            SELECT id, member_id, amount, transfer_reference
            FROM public.member_welfare_contributions
            WHERE id = %s
            FOR UPDATE;
            """,
            (transfer_id,),
        )
        transfer = cursor.fetchone()
        if not transfer:
            return None

        cursor.execute(
            """
            SELECT COALESCE(welfare_balance, 0) AS welfare_balance
            FROM public.member_welfare_balances
            WHERE member_id = %s;
            """,
            (transfer["member_id"],),
        )
        balance_row = cursor.fetchone()
        previous_balance = (
            Decimal(str(balance_row["welfare_balance"] or 0))
            if balance_row
            else Decimal("0")
        )
        cursor.execute(
            """
            SELECT COALESCE(available_savings, 0) AS available_savings
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (transfer["member_id"],),
        )
        savings_row = cursor.fetchone()
        previous_savings = (
            Decimal(str(savings_row["available_savings"] or 0))
            if savings_row
            else Decimal("0")
        )

        cursor.execute(
            """
            SELECT id, amount
            FROM public.welfare_request_member_arrears_payments
            WHERE LEFT(payment_reference, LENGTH(%s) + 1) = %s || '-'
            FOR UPDATE;
            """,
            (transfer["transfer_reference"], transfer["transfer_reference"]),
        )
        arrears_paid = sum(
            (Decimal(str(payment["amount"] or 0)) for payment in cursor.fetchall()),
            Decimal("0"),
        )
        cursor.execute(
            """
            DELETE FROM public.welfare_request_member_arrears_payments
            WHERE LEFT(payment_reference, LENGTH(%s) + 1) = %s || '-';
            """,
            (transfer["transfer_reference"], transfer["transfer_reference"]),
        )
        cursor.execute(
            """
            DELETE FROM public.member_welfare_contributions
            WHERE id = %s
            RETURNING id;
            """,
            (transfer_id,),
        )
        if not cursor.fetchone():
            return None

        cursor.execute(
            """
            SELECT COALESCE(welfare_balance, 0) AS welfare_balance
            FROM public.member_welfare_balances
            WHERE member_id = %s;
            """,
            (transfer["member_id"],),
        )
        balance_row = cursor.fetchone()
        new_balance = (
            Decimal(str(balance_row["welfare_balance"] or 0))
            if balance_row
            else Decimal("0")
        )
        cursor.execute(
            """
            SELECT COALESCE(available_savings, 0) AS available_savings
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (transfer["member_id"],),
        )
        savings_row = cursor.fetchone()
        new_savings = (
            Decimal(str(savings_row["available_savings"] or 0))
            if savings_row
            else Decimal("0")
        )
        amount = Decimal(str(transfer["amount"] or 0))
        details = (
            f"Removed welfare transfer {transfer_id} ({transfer['transfer_reference']}) "
            f"for member {transfer['member_id']}: UGX {amount:,.2f}; "
            f"reversed UGX {arrears_paid:,.2f} in linked arrears payments. "
            f"Welfare balance changed from UGX {previous_balance:,.2f} to "
            f"UGX {new_balance:,.2f}; available savings changed from "
            f"UGX {previous_savings:,.2f} to UGX {new_savings:,.2f}. "
            f"Reason: {reason}"
        )
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'member_welfare_contribution', %s,
                'treasurer_welfare_transfer_deleted', %s, %s, %s, %s, %s, NOW()
            );
            """,
            (
                str(transfer_id),
                actor_name,
                actor_role,
                details,
                str(previous_savings),
                str(new_savings),
            ),
        )
        cursor.execute(
            """
            INSERT INTO public.notifications (
                recipient_type, recipient_id, title, message, is_read,
                category, module_name, priority, action_link, delivery_status, created_at
            )
            VALUES (
                'Member', %s, 'Welfare transfer corrected', %s, FALSE,
                'Welfare', 'Welfare Support', 'Normal', '/api/welfare/view',
                'Delivered', NOW()
            );
            """,
            (
                transfer["member_id"],
                (
                    f"A welfare transfer of UGX {amount:,.2f} was removed from your "
                    f"welfare ledger. UGX {arrears_paid:,.2f} in linked arrears payments "
                    f"was also reversed. Updated welfare balance: UGX {new_balance:,.2f}; "
                    f"available savings: UGX {new_savings:,.2f}. Reason: {reason}"
                ),
            ),
        )
        return {
            "transfer": transfer,
            "arrears_paid": arrears_paid,
            "previous_balance": previous_balance,
            "welfare_balance": new_balance,
            "previous_savings": previous_savings,
            "available_savings": new_savings,
        }
