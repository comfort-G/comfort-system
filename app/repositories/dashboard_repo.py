from app.database import get_db


def get_member_dashboard_data(member_str_id: str):
    """Fetches one member's profile, financial totals, and tier inputs."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                m.member_id,
                m.full_name,
                m.role,
                m.status AS account_status,
                m.override_status,
                COALESCE(m.joined_date, m.join_date, CURRENT_DATE) AS joined_date,
                COALESCE((
                    SELECT SUM(wp.amount)
                    FROM welfare_payments wp
                    JOIN welfare_requests wr ON wr.id = wp.request_id
                    WHERE wr.member_id = m.member_id
                ), 0) + COALESCE((
                    SELECT SUM(mwc.amount)
                    FROM member_welfare_contributions mwc
                    WHERE mwc.member_id = m.member_id
                ), 0) AS total_welfare,
                COALESCE(welfare_balances.welfare_balance, 0) AS welfare_balance,
                COALESCE((
                    SELECT payouts.remaining_savings
                    FROM public.sharing_member_payouts payouts
                    WHERE payouts.member_id = m.member_id
                ), 0) AS total_savings,
                COALESCE((
                    SELECT SUM(s.amount_paid)
                    FROM subscriptions s
                    WHERE s.member_id = m.member_id
                      AND LOWER(BTRIM(COALESCE(s.status, ''))) = 'paid'
                      AND s.billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                      AND s.billing_month < (
                          DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                      )::date
                ), 0) AS current_year_contributions,
                COALESCE((
                    SELECT SUM(COALESCE(l.outstanding_balance, 0))
                    FROM loans l
                    WHERE l.member_id = m.member_id
                      AND l.status IN ('Approved', 'Active')
                ), 0) AS active_loan_balance
            FROM members m
            LEFT JOIN public.member_welfare_balances welfare_balances
                ON welfare_balances.member_id = m.member_id
            WHERE m.member_id = %s;
            """,
            (member_str_id,),
        )
        return cursor.fetchone()
