# app/repositories/sharing_repo.py
from app.database import get_db
from decimal import Decimal


def get_sharing_activation_state():
    """Fetches the current year-end sharing activation toggle set by the Chairperson."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, active, activated_on, deactivated_on, updated_at
            FROM sharing_workflow_state
            ORDER BY (id = 1) DESC, id DESC
            LIMIT 1;
            """
        )
        return cursor.fetchone()


def toggle_sharing_activation_in_db(is_active: bool):
    """Allows the Chairperson to activate or deactivate the year-end sharing cycle."""
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO public.sharing_workflow_state
                (id, active, activated_on, deactivated_on, updated_at)
            VALUES
                (
                    1,
                    %s,
                    CASE WHEN %s THEN CURRENT_DATE ELSE NULL END,
                    CASE WHEN %s THEN NULL ELSE CURRENT_DATE END,
                    NOW()
                )
            ON CONFLICT (id) DO UPDATE
            SET active = EXCLUDED.active,
                activated_on = EXCLUDED.activated_on,
                deactivated_on = EXCLUDED.deactivated_on,
                updated_at = NOW()
            RETURNING id, active, activated_on, deactivated_on;
            """,
            (is_active, is_active, is_active),
        )
        return cursor.fetchone()


def get_member_savings_total(member_str_id: str):
    """Fetches current savings after welfare transfers and disbursed sharing withdrawals."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT remaining_savings AS total_savings
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (member_str_id,),
        )
        return cursor.fetchone()


def get_interest_sharing_summary(member_str_id: str):
    """Fetches the shared payout calculation for one registered member."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                total_interest_pool,
                member_interest_paid,
                total_members,
                borrower_dividend,
                group_dividend,
                total_dividends,
                available_payout
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (member_str_id,),
        )
        return cursor.fetchone() or {
            "total_interest_pool": Decimal("0"),
            "member_interest_paid": Decimal("0"),
            "total_members": 0,
        }


def get_member_withdrawal_totals(member_str_id: str):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                reserved_amount,
                disbursed_amount
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (member_str_id,),
        )
        totals = cursor.fetchone() or {
            "reserved_amount": Decimal("0"),
            "disbursed_amount": Decimal("0"),
        }
        cursor.execute(
            """
            SELECT id, amount, status, requested_on, approved_on, disbursed_on,
                   review_comment
            FROM public.sharing_withdrawal_requests
            WHERE member_id = %s
            ORDER BY requested_on DESC, id DESC
            LIMIT 20;
            """,
            (member_str_id,),
        )
        totals["requests"] = cursor.fetchall()
        return totals


def create_withdrawal_if_available(
    member_str_id: str,
    amount: Decimal,
    actor_name: str,
    actor_role: str,
):
    """Creates a pending request and reserves against the member's full payout."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT active
            FROM sharing_workflow_state
            ORDER BY (id = 1) DESC, id DESC
            LIMIT 1
            FOR UPDATE;
            """
        )
        state = cursor.fetchone()
        if not state or not state.get("active", False):
            return {"error": "sharing_inactive"}

        cursor.execute(
            "SELECT id FROM members WHERE member_id = %s FOR UPDATE;",
            (member_str_id,),
        )
        if not cursor.fetchone():
            return {"error": "member_not_found"}

        cursor.execute(
            """
            SELECT available_payout
            FROM public.sharing_member_payouts
            WHERE member_id = %s;
            """,
            (member_str_id,),
        )
        balance = cursor.fetchone()
        available = Decimal(str(balance["available_payout"] or 0)) if balance else Decimal("0")
        if amount > available:
            return {"error": "insufficient_payout", "available": available}

        cursor.execute(
            """
            INSERT INTO sharing_withdrawal_requests (member_id, amount, status, requested_on)
            VALUES (%s, %s, 'Pending', NOW())
            RETURNING id, status, requested_on;
            """,
            (member_str_id, amount),
        )
        withdrawal = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'sharing_withdrawal', %s, 'sharing_withdrawal_requested',
                %s, %s, %s, %s, %s, NOW()
            );
            """,
            (
                str(withdrawal["id"]),
                actor_name,
                actor_role,
                f"Member requested UGX {amount:,.2f}; awaiting Chairperson review.",
                str(available),
                str(available - amount),
            ),
        )
        return {"withdrawal": withdrawal, "available": available}


def get_withdrawal_queue():
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                wr.id, wr.member_id, m.full_name, wr.amount, wr.status,
                wr.requested_on, wr.approved_by, wr.approved_on,
                wr.disbursed_by, wr.disbursed_on, wr.review_comment
            FROM public.sharing_withdrawal_requests wr
            JOIN public.members m ON m.member_id = wr.member_id
            WHERE LOWER(BTRIM(wr.status)) IN ('pending', 'approved')
            ORDER BY wr.requested_on ASC, wr.id ASC;
            """
        )
        return cursor.fetchall()


def review_withdrawal(
    withdrawal_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str,
):
    """Chairperson approves or rejects a pending sharing request."""
    status = "Approved" if decision == "approve" else "Rejected"
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE public.sharing_withdrawal_requests
            SET status = %s,
                approved_by = CASE WHEN %s = 'Approved' THEN %s ELSE approved_by END,
                approved_role = CASE WHEN %s = 'Approved' THEN %s ELSE approved_role END,
                approved_on = CASE WHEN %s = 'Approved' THEN NOW() ELSE approved_on END,
                rejected_by = CASE WHEN %s = 'Rejected' THEN %s ELSE rejected_by END,
                rejected_role = CASE WHEN %s = 'Rejected' THEN %s ELSE rejected_role END,
                rejected_on = CASE WHEN %s = 'Rejected' THEN NOW() ELSE rejected_on END,
                review_comment = %s
            WHERE id = %s AND LOWER(BTRIM(status)) = 'pending'
            RETURNING id, member_id, amount, status;
            """,
            (
                status,
                status, actor_name,
                status, actor_role,
                status,
                status, actor_name,
                status, actor_role,
                status,
                comment, withdrawal_id,
            ),
        )
        withdrawal = cursor.fetchone()
        if not withdrawal:
            return None

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES ('sharing_withdrawal', %s, %s, %s, %s, %s, 'Pending', %s, NOW());
            """,
            (
                str(withdrawal_id),
                f"sharing_withdrawal_{status.casefold()}",
                actor_name,
                actor_role,
                comment or f"Sharing withdrawal {status.casefold()} by Chairperson.",
                status,
            ),
        )
        return withdrawal


def disburse_withdrawal(withdrawal_id: int, actor_name: str, actor_role: str):
    """Treasurer records the actual payment of an approved request."""
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE public.sharing_withdrawal_requests
            SET status = 'Paid', disbursed_by = %s, disbursed_role = %s,
                disbursed_on = NOW()
            WHERE id = %s AND LOWER(BTRIM(status)) = 'approved'
            RETURNING id, member_id, amount, status;
            """,
            (actor_name, actor_role, withdrawal_id),
        )
        withdrawal = cursor.fetchone()
        if not withdrawal:
            return None

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'sharing_withdrawal', %s, 'sharing_withdrawal_disbursed',
                %s, %s, %s, 'Approved', 'Paid', NOW()
            );
            """,
            (
                str(withdrawal_id),
                actor_name,
                actor_role,
                f"Disbursed UGX {withdrawal['amount']:,.2f} to member {withdrawal['member_id']}.",
            ),
        )
        return withdrawal