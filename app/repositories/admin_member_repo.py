# app/repositories/admin_member_repo.py
from app.database import get_db
import logging


logger = logging.getLogger("uvicorn")

def get_all_members_with_financials():
    """
    Fetches all members along with their total paid welfare,
    outstanding subscription debt, and any manual status override.
    """
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT 
                m.id, 
                m.member_id, 
                m.full_name, 
                m.email, 
                m.phone, 
                m.role, 
                m.status AS account_status,
                m.override_status, -- Fetches Chairperson's manual override if set
                m.suspension_reason,
                m.suspended_at,
                COALESCE(m.joined_date, m.join_date, CURRENT_DATE) as joined_date,
                COALESCE(w.total_welfare, 0) AS total_welfare,
                COALESCE(welfare_balances.welfare_balance, 0) AS welfare_balance,
                COALESCE(s.current_year_contributions, 0) AS current_year_contributions
            FROM members m
            LEFT JOIN (
                    SELECT
                        member_id,
                        SUM(amount) FILTER (WHERE source <> 'request') AS total_welfare
                    FROM (
                        SELECT wr.member_id, wp.amount, 'payment' AS source
                        FROM welfare_payments wp
                        JOIN welfare_requests wr ON wr.id = wp.request_id
                        UNION ALL
                        SELECT member_id, amount, 'contribution' AS source
                        FROM member_welfare_contributions
                        UNION ALL
                        SELECT member_id, welfare_amount, 'request' AS source
                        FROM public.welfare_request_member_contributions
                    ) welfare_ledger
                    GROUP BY member_id
                ) w ON m.member_id = w.member_id
            LEFT JOIN public.member_welfare_balances welfare_balances
                ON welfare_balances.member_id = m.member_id
            LEFT JOIN (
                SELECT
                    member_id,
                    SUM(CASE
                        WHEN billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                          AND billing_month < (
                              DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                          )::date
                        THEN COALESCE(amount_paid, 0)
                        ELSE 0
                    END) AS current_year_contributions
                FROM subscriptions
                WHERE LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                GROUP BY member_id
            ) s ON m.member_id = s.member_id
            ORDER BY COALESCE(m.joined_date, m.join_date, CURRENT_DATE) DESC;
            """
        )
        return cursor.fetchall()

def set_member_status_override(member_str_id: str, override_status: str | None):
    """Allows the Chairperson to set or clear a manual status override for a member."""
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE members
            SET override_status = %s
            WHERE member_id = %s
            RETURNING member_id, override_status;
            """,
            (override_status, member_str_id)
        )
        return cursor.fetchone()


def suspend_member_account(
    member_str_id: str,
    reason: str,
    actor_name: str,
    actor_role: str,
):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT status
            FROM public.members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_str_id,),
        )
        member = cursor.fetchone()
        if member is None:
            return {"error": "member_not_found"}
        if (member.get("status") or "").strip().casefold() == "suspended":
            return {"error": "already_suspended"}

        cursor.execute(
            """
            UPDATE public.members
            SET suspended_previous_status = status,
                status = 'Suspended',
                suspension_reason = %s,
                suspended_by = %s,
                suspended_at = NOW()
            WHERE member_id = %s
            RETURNING member_id, status, suspension_reason, suspended_at;
            """,
            (reason, actor_name, member_str_id),
        )
        suspended_member = cursor.fetchone()
        if suspended_member is None:
            raise RuntimeError("Suspension update returned no member record.")
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'member_account', %s, 'member_account_suspended',
                %s, %s, %s, %s, 'Suspended', NOW()
            );
            """,
            (
                member_str_id,
                actor_name,
                actor_role,
                f"Member account suspended. Reason: {reason}",
                member["status"] or "",
            ),
        )
        return suspended_member


def restore_member_account(
    member_str_id: str,
    reason: str,
    actor_name: str,
    actor_role: str,
):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT status, suspended_previous_status
            FROM public.members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_str_id,),
        )
        member = cursor.fetchone()
        if member is None:
            return {"error": "member_not_found"}
        if (member.get("status") or "").strip().casefold() != "suspended":
            return {"error": "not_suspended"}

        cursor.execute(
            """
            UPDATE public.members
            SET status = COALESCE(NULLIF(suspended_previous_status, ''), 'Active'),
                suspended_previous_status = NULL,
                suspension_reason = NULL,
                suspended_by = NULL,
                suspended_at = NULL
            WHERE member_id = %s
            RETURNING member_id, status;
            """,
            (member_str_id,),
        )
        restored_member = cursor.fetchone()
        if restored_member is None:
            raise RuntimeError("Account restoration returned no member record.")
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'member_account', %s, 'member_account_restored',
                %s, %s, %s, 'Suspended', %s, NOW()
            );
            """,
            (
                member_str_id,
                actor_name,
                actor_role,
                f"Member account restored. Reason: {reason}",
                restored_member["status"],
            ),
        )
        return restored_member


def notify_executives_of_suspended_login(member_id: str, member_name: str) -> bool:
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO public.notifications (
                recipient_type, recipient_id, title, message, is_read,
                category, module_name, priority, action_link,
                delivery_status, created_at
            )
            SELECT
                'Executive', members.member_id,
                'Suspended account login attempt',
                %s, FALSE, 'Account security', 'Executive Action Center',
                'High', '/api/executive-actions/view', 'Delivered', NOW()
            FROM public.members members
            WHERE LOWER(BTRIM(COALESCE(members.role, ''))) IN (
                'chairperson', 'vice chairperson', 'treasurer',
                'secretary', 'welfare', 'welfare officer'
            );
            """,
            (
                f"Suspended member {member_name} ({member_id}) entered valid "
                "credentials and attempted to log in. Contact the member if needed."
            ),
        )
        if cursor.rowcount == 0:
            logger.error(
                "Suspended login attempt for member %s could not notify any executives "
                "because no executive accounts were found.",
                member_id,
            )
            return False
        return True