from typing import Any

from app.database import get_db


def fetch_home_records(
    member_id: str,
    include_global_financials: bool = False,
) -> dict[str, Any] | None:
    """Fetches the member dashboard and membership summary records."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                member_id,
                full_name,
                role,
                avatar_url,
                status AS account_status,
                override_status,
                COALESCE(joined_date, join_date, CURRENT_DATE) AS joined_date
            FROM members
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        member = cursor.fetchone()
        if not member:
            return None

        cursor.execute(
            """
            SELECT
                COALESCE((
                    SELECT payouts.remaining_savings
                    FROM public.sharing_member_payouts payouts
                    WHERE payouts.member_id = %s
                ), 0) AS total_savings,
                COALESCE((
                    SELECT SUM(s.amount_paid)
                    FROM subscriptions s
                    WHERE s.member_id = %s
                      AND LOWER(BTRIM(COALESCE(s.status, ''))) = 'paid'
                ), 0) AS total_contributions,
                COALESCE((
                    SELECT SUM(s.amount_paid)
                    FROM subscriptions s
                    WHERE s.member_id = %s
                      AND LOWER(BTRIM(COALESCE(s.status, ''))) = 'paid'
                      AND s.billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                      AND s.billing_month < (
                          DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                      )::date
                ), 0.0) AS current_year_contributions,
                COALESCE((
                    SELECT COUNT(*)
                    FROM subscriptions s
                    WHERE s.member_id = %s
                      AND LOWER(BTRIM(COALESCE(s.status, ''))) = 'pending'
                ), 0) AS pending_subscription_count,
                COALESCE((
                    SELECT SUM(wp.amount)
                    FROM welfare_payments wp
                    JOIN welfare_requests wr ON wr.id = wp.request_id
                    WHERE wr.member_id = %s
                ), 0.0) + COALESCE((
                    SELECT SUM(mwc.amount)
                    FROM member_welfare_contributions mwc
                    WHERE mwc.member_id = %s
                ), 0.0) AS total_welfare,
                COALESCE((
                    SELECT welfare_balances.welfare_balance
                    FROM public.member_welfare_balances welfare_balances
                    WHERE welfare_balances.member_id = %s
                ), 0) AS welfare_balance,
                COALESCE(NULLIF((
                    SELECT SUM(COALESCE(lr.principal_paid, 0))
                    FROM loan_repayments lr
                    WHERE lr.member_id = %s
                ), 0), (
                    SELECT SUM(GREATEST(
                        COALESCE(l.amount_requested, 0) -
                        COALESCE(l.outstanding_balance, 0),
                        0
                    ))
                    FROM loans l
                    WHERE l.member_id = %s
                      AND LOWER(BTRIM(COALESCE(l.status, ''))) IN ('approved', 'active')
                ), 0.0) AS loan_principal_paid,
                COALESCE(NULLIF((
                    SELECT SUM(COALESCE(lr.interest_paid, 0))
                    FROM loan_repayments lr
                    WHERE lr.member_id = %s
                ), 0), (
                    SELECT SUM(COALESCE(l.total_interest_collected, 0))
                    FROM loans l
                    WHERE l.member_id = %s
                ), 0.0) AS loan_interest_paid,
                COALESCE((
                    SELECT SUM(COALESCE(l.amount_requested, 0))
                    FROM loans l
                    WHERE l.member_id = %s
                ), 0.0) AS total_loan_amount_requested,
                COALESCE((
                    SELECT SUM(COALESCE(l.total_interest_collected, 0))
                    FROM loans l
                    WHERE l.member_id = %s
                ), 0.0) AS total_interest_collected,
                COALESCE((
                    SELECT SUM(COALESCE(l.outstanding_balance, 0))
                    FROM loans l
                    WHERE l.member_id = %s
                      AND LOWER(BTRIM(COALESCE(l.status, ''))) IN ('approved', 'active')
                ), 0.0) AS active_loan_balance,
                COALESCE(NULLIF((
                    SELECT SUM(COALESCE(lr.principal_paid, 0) + COALESCE(lr.interest_paid, 0))
                    FROM loan_repayments lr
                    WHERE lr.member_id = %s
                ), 0), (
                    SELECT SUM(
                        GREATEST(
                            COALESCE(l.amount_requested, 0) -
                            COALESCE(l.outstanding_balance, 0),
                            0
                        ) + COALESCE(l.total_interest_collected, 0)
                    )
                    FROM loans l
                    WHERE l.member_id = %s
                      AND LOWER(BTRIM(COALESCE(l.status, ''))) IN ('approved', 'active')
                ), 0.0) AS total_loan_repayments,
                COALESCE((
                    SELECT SUM(COALESCE(l.amount_requested, 0) - COALESCE(l.outstanding_balance, 0))
                    FROM loans l
                    WHERE l.member_id = %s
                      AND LOWER(BTRIM(COALESCE(l.status, ''))) IN ('approved', 'active')
                ), 0.0) AS principal_recovered_from_loans;
            """,
            (member_id,) * 17,
        )
        member_financials = cursor.fetchone()

        global_financials = None
        global_running_loans = None
        if include_global_financials:
            cursor.execute(
                """
                WITH subscription_totals AS (
                    SELECT
                        COALESCE(SUM(amount_paid), 0) AS total_paid,
                        COALESCE(SUM(amount_paid) FILTER (
                            WHERE billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                              AND billing_month < (
                                  DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                              )::date
                        ), 0) AS current_year_paid
                    FROM public.subscriptions
                    WHERE LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                ),
                welfare_totals AS (
                    SELECT
                        COALESCE((
                            SELECT SUM(welfare_balance)
                            FROM public.member_welfare_balances
                        ), 0) AS account_balance,
                        COALESCE((
                            SELECT SUM(total_contributed)
                            FROM public.member_welfare_balances
                        ), 0) AS total_funding
                ),
                member_savings_totals AS (
                    SELECT COALESCE(SUM(remaining_savings), 0) AS total_member_savings
                    FROM public.sharing_member_payouts
                ),
                principal_repayments AS (
                    SELECT loan_id, SUM(COALESCE(principal_paid, 0)) AS principal_paid
                    FROM public.loan_repayments
                    GROUP BY loan_id
                ),
                loan_totals AS (
                    SELECT
                        COUNT(*) FILTER (WHERE running.status IN ('approved', 'active'))
                            AS running_loan_count,
                        COALESCE(SUM(running.outstanding_balance) FILTER (
                            WHERE running.status IN ('approved', 'active')
                        ), 0) AS running_loan_balance,
                        COALESCE(SUM(running.principal_remaining) FILTER (
                            WHERE running.status IN ('approved', 'active')
                        ), 0) AS unpaid_loan_principal,
                        COALESCE(SUM(total_interest_collected), 0) AS recorded_interest
                    FROM (
                        SELECT
                            LOWER(BTRIM(COALESCE(loans.status, ''))) AS status,
                            loans.outstanding_balance,
                            loans.total_interest_collected,
                            GREATEST(
                                COALESCE(loans.amount_requested, 0)
                                    - COALESCE(principal_repayments.principal_paid, 0),
                                0
                            ) AS principal_remaining
                        FROM public.loans loans
                        LEFT JOIN principal_repayments
                            ON principal_repayments.loan_id = loans.loan_id
                    ) running
                ),
                repayment_totals AS (
                    SELECT COALESCE(SUM(interest_paid), 0) AS interest_paid
                    FROM public.loan_repayments
                )
                SELECT
                    subscription_totals.total_paid AS total_subscription_contributions,
                    subscription_totals.current_year_paid AS current_year_subscription_contributions,
                    welfare_totals.account_balance AS welfare_account_balance,
                    welfare_totals.total_funding AS total_welfare_contributions,
                    member_savings_totals.total_member_savings,
                    loan_totals.running_loan_count,
                    loan_totals.running_loan_balance,
                    loan_totals.unpaid_loan_principal,
                    member_savings_totals.total_member_savings
                        - loan_totals.unpaid_loan_principal AS group_working_capital,
                    COALESCE(
                        NULLIF(repayment_totals.interest_paid, 0),
                        loan_totals.recorded_interest,
                        0
                    ) AS total_loan_interest_collected
                FROM subscription_totals
                CROSS JOIN welfare_totals
                CROSS JOIN member_savings_totals
                CROSS JOIN loan_totals
                CROSS JOIN repayment_totals;
                """
            )
            global_financials = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                    l.loan_id,
                    l.member_id,
                    m.full_name,
                    l.status,
                    l.amount_requested,
                    l.outstanding_balance,
                    l.interest_accumulated,
                    l.approved_date,
                    COALESCE(
                        l.last_interest_applied_date,
                        l.last_interest_applied_at
                    ) AS last_interest_date
                FROM public.loans l
                JOIN public.members m ON m.member_id = l.member_id
                WHERE LOWER(BTRIM(COALESCE(l.status, ''))) IN ('approved', 'active')
                ORDER BY l.approved_date DESC NULLS LAST, l.loan_id DESC;
                """
            )
            global_running_loans = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                loan_id,
                amount_requested,
                outstanding_balance,
                status,
                applied_date,
                approved_date,
                last_interest_applied_date,
                last_interest_applied_at
            FROM loans
            WHERE member_id = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) IN ('pending', 'approved', 'active')
            ORDER BY approved_date DESC NULLS LAST, applied_date DESC NULLS LAST
            LIMIT 1;
            """,
            (member_id,),
        )
        current_loan = cursor.fetchone()

        cursor.execute(
            """
            SELECT id, title, message, module_name, created_at
            FROM notifications
            WHERE UPPER(BTRIM(COALESCE(recipient_id, ''))) = 'ALL'
              AND LOWER(BTRIM(COALESCE(category, ''))) = 'announcement'
            ORDER BY created_at DESC, id DESC
            LIMIT 12;
            """
        )
        announcements = cursor.fetchall()

        records: dict[str, Any] = {
            "member": member,
            "member_financials": member_financials,
            "global_financials": global_financials,
            "global_running_loans": global_running_loans,
            "current_loan": current_loan,
            "announcements": announcements,
        }
        cursor.execute(
            """
            SELECT
                m.member_id,
                m.full_name,
                m.status AS account_status,
                COALESCE(m.joined_date, m.join_date, CURRENT_DATE) AS joined_date,
                COALESCE(payouts.remaining_savings, 0) AS total_savings,
                COALESCE(s.current_year_contributions, 0) AS current_year_contributions
            FROM members m
            LEFT JOIN public.sharing_member_payouts payouts
                ON payouts.member_id = m.member_id
            LEFT JOIN (
                SELECT
                    member_id,
                    SUM(COALESCE(amount_paid, 0)) AS total_savings,
                    SUM(
                        CASE
                            WHEN billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                              AND billing_month < (
                                  DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                              )::date
                            THEN COALESCE(amount_paid, 0)
                            ELSE 0
                        END
                    ) AS current_year_contributions
                FROM subscriptions
                WHERE LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                GROUP BY member_id
            ) s ON s.member_id = m.member_id
            ORDER BY m.full_name, m.member_id;
            """
        )
        members = cursor.fetchall()
        records["members"] = members
        return records


def publish_announcement(title: str, content: str, author_name: str) -> dict[str, Any]:
    """Stores a broadcast announcement using the existing notifications ledger."""
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO notifications (
                recipient_type,
                recipient_id,
                title,
                message,
                is_read,
                category,
                module_name,
                priority,
                action_link,
                delivery_status,
                created_at
            )
            VALUES (
                'Member',
                'ALL',
                %s,
                %s,
                FALSE,
                'Announcement',
                'Portal',
                'Normal',
                NULL,
                'Delivered',
                NOW()
            )
            RETURNING id, title, message, created_at;
            """,
            (title, f"Posted by: {author_name}\n\n{content}"),
        )
        return cursor.fetchone()
