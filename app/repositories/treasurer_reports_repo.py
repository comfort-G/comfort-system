from collections.abc import Mapping, Sequence
from typing import Any

from app.database import get_db


def fetch_treasurer_report() -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(s.status, ''))) = 'paid'
                ) AS paid_count,
                COALESCE(SUM(s.amount_paid) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(s.status, ''))) = 'paid'
                ), 0) AS paid_total,
                COUNT(*) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(s.status, ''))) <> 'paid'
                ) AS other_count,
                COALESCE(SUM(s.amount_paid) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(s.status, ''))) <> 'paid'
                ), 0) AS other_total
            FROM public.subscriptions AS s;
            """
        )
        subscriptions = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COUNT(*) AS loan_count,
                COALESCE(SUM(CASE
                    WHEN LOWER(BTRIM(COALESCE(l.status, '')))
                        NOT IN ('pending', 'rejected', 'reversed')
                    THEN l.amount_requested ELSE 0 END), 0) AS approved_principal,
                COALESCE(SUM(CASE
                    WHEN LOWER(BTRIM(COALESCE(l.status, '')))
                        NOT IN ('rejected', 'reversed', 'paid', 'cleared', 'completed', 'settled', 'closed')
                    THEN l.outstanding_balance ELSE 0 END), 0) AS outstanding_balance,
                COUNT(*) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(l.status, ''))) = 'pending'
                ) AS pending_count
            FROM public.loans AS l;
            """
        )
        loans = cursor.fetchone()
        cursor.execute(
            """
            WITH lr AS (
                SELECT
                    loan_repayments.loan_id,
                    COUNT(*) AS repayment_count,
                    SUM(COALESCE(loan_repayments.principal_paid, 0)) AS principal_paid,
                    SUM(COALESCE(loan_repayments.interest_paid, 0)) AS interest_paid
                FROM public.loan_repayments AS loan_repayments
                GROUP BY loan_repayments.loan_id
            )
            SELECT
                COALESCE(SUM(lr.principal_paid), 0) AS principal_repaid,
                COALESCE(SUM(
                    CASE
                        WHEN COALESCE(lr.repayment_count, 0) > 0
                            THEN lr.interest_paid
                        WHEN l.total_interest_collected > 0
                          AND LOWER(BTRIM(COALESCE(l.status, ''))) IN (
                              'paid', 'cleared', 'completed', 'settled', 'closed'
                          )
                            THEN l.total_interest_collected
                        ELSE 0
                    END
                ), 0) AS interest_collected
            FROM public.loans AS l
            LEFT JOIN lr
                ON lr.loan_id = l.loan_id;
            """
        )
        loans.update(cursor.fetchone())

        cursor.execute(
            """
            SELECT
                COUNT(*) AS member_count,
                COALESCE(SUM(payouts.savings), 0) AS savings,
                COALESCE(SUM(payouts.available_savings), 0) AS available_savings,
                COALESCE(SUM(payouts.borrower_dividend), 0) AS borrower_dividends,
                COALESCE(SUM(payouts.group_dividend), 0) AS group_dividends,
                COALESCE(SUM(payouts.available_payout), 0) AS available_payout
            FROM public.sharing_member_payouts AS payouts;
            """
        )
        sharing = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(swr.amount) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(swr.status, ''))) IN ('paid', 'disbursed')
                ), 0) AS disbursed,
                COALESCE(SUM(swr.amount) FILTER (
                    WHERE LOWER(BTRIM(COALESCE(swr.status, ''))) IN ('pending', 'approved')
                ), 0) AS reserved
            FROM public.sharing_withdrawal_requests AS swr;
            """
        )
        sharing.update(cursor.fetchone())

        cursor.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(wb.welfare_balance)
                    FROM public.member_welfare_balances AS wb
                ), 0) AS account_balance,
                COALESCE((SELECT SUM(mwc.amount)
                    FROM public.member_welfare_contributions AS mwc), 0)
                    AS total_funding,
                COALESCE((SELECT SUM(wrd.amount)
                    FROM public.welfare_request_disbursements AS wrd), 0)
                + COALESCE((SELECT SUM(wp.amount)
                    FROM public.welfare_payments AS wp), 0)
                - COALESCE((SELECT SUM(reversal.amount_returned)
                    FROM public.welfare_disbursement_reversals AS reversal), 0)
                    AS total_disbursed,
                COALESCE((SELECT SUM(reversal.amount_returned)
                    FROM public.welfare_disbursement_reversals AS reversal), 0)
                    AS total_returned,
                COALESCE((SELECT SUM(wrmc.welfare_amount)
                    FROM public.welfare_request_member_contributions AS wrmc), 0)
                    AS welfare_balance_assessed,
                COALESCE((SELECT SUM(wrmc.savings_amount)
                    FROM public.welfare_request_member_contributions AS wrmc), 0)
                    AS savings_assessed,
                COALESCE((SELECT SUM(arp.amount)
                    FROM public.welfare_request_member_arrears_payments AS arp), 0)
                    AS arrears_paid,
                COALESCE((
                    SELECT SUM(GREATEST(
                        wrmc.outstanding_amount
                            - COALESCE(arrears.paid, 0),
                        0
                    ))
                    FROM public.welfare_request_member_contributions AS wrmc
                    LEFT JOIN (
                        SELECT
                            arp.request_id,
                            arp.member_id,
                            SUM(arp.amount) AS paid
                        FROM public.welfare_request_member_arrears_payments AS arp
                        GROUP BY arp.request_id, arp.member_id
                    ) AS arrears
                        ON arrears.request_id = wrmc.request_id
                       AND arrears.member_id = wrmc.member_id
                ), 0) AS member_arrears;
            """
        )
        welfare = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                wb.member_id,
                m.full_name,
                wb.total_contributed,
                wb.amount_assessed,
                wb.arrears_paid,
                wb.welfare_balance
            FROM public.member_welfare_balances AS wb
            JOIN public.members AS m
                ON m.member_id = wb.member_id
            ORDER BY m.full_name, wb.member_id;
            """
        )
        welfare_member_balances = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                s.id,
                s.member_id,
                m.full_name,
                s.billing_month,
                s.amount_paid,
                s.status
            FROM public.subscriptions AS s
            LEFT JOIN public.members AS m
                ON m.member_id = s.member_id
            ORDER BY s.billing_month DESC, s.id DESC;
            """
        )
        subscription_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                proof.proof_id,
                proof.member_id,
                proof.member_name,
                proof.subscription_month,
                proof.subscription_year,
                CASE
                    WHEN LOWER(BTRIM(COALESCE(proof.verification_status, ''))) = 'paid'
                        THEN proof.amount_paid
                    ELSE NULL
                END AS amount_paid,
                proof.payment_method,
                proof.transaction_reference,
                proof.verification_status,
                proof.upload_timestamp,
                proof.verified_by,
                proof.verification_date,
                proof.verification_comment
            FROM public.subscription_payment_proofs AS proof
            ORDER BY proof.upload_timestamp DESC, proof.proof_id DESC;
            """
        )
        subscription_proofs = cursor.fetchall()

        cursor.execute(
            """
            WITH lr AS (
                SELECT
                    loan_repayments.loan_id,
                    SUM(COALESCE(loan_repayments.principal_paid, 0)) AS principal_paid,
                    SUM(COALESCE(loan_repayments.interest_paid, 0)) AS interest_paid,
                    COUNT(*) AS repayment_count
                FROM public.loan_repayments AS loan_repayments
                GROUP BY loan_repayments.loan_id
            )
            SELECT
                l.loan_id,
                l.member_id,
                m.full_name,
                l.amount_requested,
                l.outstanding_balance,
                l.status,
                l.applied_date,
                COALESCE(lr.principal_paid, 0) AS principal_paid,
                CASE
                    WHEN COALESCE(lr.repayment_count, 0) > 0
                        THEN COALESCE(lr.interest_paid, 0)
                    WHEN l.total_interest_collected > 0
                      AND LOWER(BTRIM(COALESCE(l.status, ''))) IN (
                          'paid', 'cleared', 'completed', 'settled', 'closed'
                      )
                        THEN l.total_interest_collected
                    ELSE 0
                END AS interest_paid
            FROM public.loans AS l
            LEFT JOIN public.members AS m
                ON m.member_id = l.member_id
            LEFT JOIN lr
                ON lr.loan_id = l.loan_id
            ORDER BY l.applied_date DESC, l.loan_id DESC;
            """
        )
        loan_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                lr.loan_id,
                lr.member_id,
                m.full_name,
                lr.principal_paid,
                lr.interest_paid
            FROM public.loan_repayments AS lr
            LEFT JOIN public.members AS m
                ON m.member_id = lr.member_id
            ORDER BY lr.loan_id DESC, lr.member_id;
            """
        )
        loan_repayment_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                m.member_id,
                m.full_name,
                payouts.savings,
                payouts.available_savings,
                payouts.borrower_dividend,
                payouts.group_dividend,
                payouts.disbursed_amount,
                payouts.reserved_amount,
                payouts.available_payout
            FROM public.sharing_member_payouts payouts
            JOIN public.members AS m
                ON m.member_id = payouts.member_id
            ORDER BY m.full_name, m.member_id;
            """
        )
        sharing_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                swr.id,
                swr.member_id,
                m.full_name,
                swr.amount,
                swr.status,
                swr.requested_on,
                swr.approved_by,
                swr.approved_on,
                swr.rejected_by,
                swr.rejected_on,
                swr.disbursed_by,
                swr.disbursed_on,
                swr.review_comment
            FROM public.sharing_withdrawal_requests AS swr
            LEFT JOIN public.members AS m
                ON m.member_id = swr.member_id
            ORDER BY swr.requested_on DESC, swr.id DESC;
            """
        )
        sharing_withdrawal_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                wr.id,
                wr.case_number,
                wr.member_id,
                wr.member_name,
                wr.support_category,
                wr.beneficiary_name,
                wr.beneficiary_relationship,
                wr.status,
                wr.current_stage,
                wr.created_at,
                COALESCE(disbursements.target_amount, 0) AS target_amount,
                COALESCE(disbursements.amount, 0) AS disbursed_amount,
                disbursements.payment_reference,
                COALESCE(contributions.welfare_amount, 0) AS welfare_funding,
                COALESCE(contributions.savings_amount, 0) AS savings_funding,
                COALESCE(contributions_due.member_arrears, 0) AS member_arrears
            FROM public.welfare_requests AS wr
            LEFT JOIN (
                SELECT
                    payment_rows.request_id,
                    MAX(payment_rows.target_amount) AS target_amount,
                    SUM(payment_rows.amount) AS amount,
                    STRING_AGG(
                        payment_rows.payment_reference,
                        ', ' ORDER BY payment_rows.disbursed_at
                    )
                        AS payment_reference
                FROM (
                    SELECT
                        wrd.request_id,
                        wrd.target_amount,
                        wrd.amount,
                        wrd.payment_reference,
                        wrd.disbursed_at
                    FROM public.welfare_request_disbursements AS wrd
                    UNION ALL
                    SELECT
                        reversal.request_id,
                        0::numeric AS target_amount,
                        -reversal.amount_returned AS amount,
                        'Emergency reversal'::text AS payment_reference,
                        reversal.returned_at AS disbursed_at
                    FROM public.welfare_disbursement_reversals AS reversal
                    UNION ALL
                    SELECT
                        wp.request_id,
                        0::numeric AS target_amount,
                        wp.amount,
                        NULL::text AS payment_reference,
                        NULL::timestamp AS disbursed_at
                    FROM public.welfare_payments AS wp
                ) AS payment_rows
                GROUP BY payment_rows.request_id
            ) AS disbursements
                ON disbursements.request_id = wr.id
            LEFT JOIN (
                SELECT
                    wrmc.request_id,
                    SUM(wrmc.welfare_amount) AS welfare_amount,
                    SUM(wrmc.savings_amount) AS savings_amount,
                    SUM(wrmc.outstanding_amount) AS outstanding_amount
                FROM public.welfare_request_member_contributions AS wrmc
                GROUP BY wrmc.request_id
            ) AS contributions
                ON contributions.request_id = wr.id
            LEFT JOIN (
                SELECT
                    wrmc.request_id,
                    SUM(GREATEST(
                        wrmc.outstanding_amount - COALESCE(arrears.paid, 0),
                        0
                    )) AS member_arrears
                FROM public.welfare_request_member_contributions AS wrmc
                LEFT JOIN (
                    SELECT
                        arp.request_id,
                        arp.member_id,
                        SUM(arp.amount) AS paid
                    FROM public.welfare_request_member_arrears_payments AS arp
                    GROUP BY arp.request_id, arp.member_id
                ) AS arrears
                    ON arrears.request_id = wrmc.request_id
                   AND arrears.member_id = wrmc.member_id
                GROUP BY wrmc.request_id
            ) AS contributions_due
                ON contributions_due.request_id = wr.id
            ORDER BY wr.created_at DESC, wr.id DESC;
            """
        )
        welfare_requests = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                c.request_id,
                wr.case_number,
                m.member_id,
                m.full_name,
                CASE
                    WHEN c.is_exempt THEN 'Exempt (probation when claim was filed)'
                    ELSE 'Eligible'
                END AS contribution_status,
                c.target_amount,
                c.welfare_amount,
                c.savings_amount,
                GREATEST(
                    c.outstanding_amount - COALESCE(ar.paid, 0),
                    0
                ) AS outstanding_amount
            FROM public.welfare_request_member_contributions AS c
            JOIN public.welfare_requests AS wr
                ON wr.id = c.request_id
            JOIN public.members AS m
                ON m.member_id = c.member_id
            LEFT JOIN (
                SELECT
                    arp.request_id,
                    arp.member_id,
                    SUM(arp.amount) AS paid
                FROM public.welfare_request_member_arrears_payments AS arp
                GROUP BY arp.request_id, arp.member_id
            ) AS ar
                ON ar.request_id = c.request_id
               AND ar.member_id = c.member_id
            ORDER BY wr.created_at DESC, m.full_name, m.member_id;
            """
        )
        welfare_contributors = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                d.id,
                d.request_id,
                wr.case_number,
                wr.member_id AS applicant_member_id,
                wr.member_name AS applicant_name,
                wr.support_category,
                wr.beneficiary_name,
                wr.beneficiary_relationship,
                d.target_amount,
                d.amount,
                d.disbursed_by,
                d.disbursed_role,
                d.payment_reference,
                d.disbursed_at
            FROM (
                SELECT
                    wrd.id,
                    wrd.request_id,
                    wrd.target_amount,
                    wrd.amount,
                    wrd.disbursed_by,
                    wrd.disbursed_role,
                    wrd.payment_reference,
                    wrd.disbursed_at
                FROM public.welfare_request_disbursements AS wrd
                UNION ALL
                SELECT
                    reversal.id,
                    reversal.request_id,
                    0::numeric AS target_amount,
                    -reversal.amount_returned AS amount,
                    reversal.actor_name AS disbursed_by,
                    reversal.actor_role AS disbursed_role,
                    'Emergency reversal'::text AS payment_reference,
                    reversal.returned_at AS disbursed_at
                FROM public.welfare_disbursement_reversals AS reversal
                UNION ALL
                SELECT
                    NULL::bigint AS id,
                    wp.request_id,
                    0::numeric AS target_amount,
                    wp.amount,
                    'Legacy record' AS disbursed_by,
                    'System' AS disbursed_role,
                    NULL::text AS payment_reference,
                    NULL::timestamp AS disbursed_at
                FROM public.welfare_payments AS wp
            ) AS d
            JOIN public.welfare_requests AS wr
                ON wr.id = d.request_id
            ORDER BY d.disbursed_at DESC, d.id DESC;
            """
        )
        welfare_disbursement_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                mwc.id,
                mwc.transfer_reference,
                mwc.member_id,
                m.full_name,
                mwc.amount,
                mwc.created_by,
                mwc.created_by_role,
                mwc.created_at
            FROM public.member_welfare_contributions AS mwc
            LEFT JOIN public.members AS m
                ON m.member_id = mwc.member_id
            ORDER BY mwc.created_at DESC, mwc.id DESC;
            """
        )
        welfare_contribution_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                arp.id,
                arp.payment_reference,
                arp.request_id,
                wr.case_number,
                arp.member_id,
                m.full_name,
                arp.amount,
                arp.created_by,
                arp.created_by_role,
                arp.created_at
            FROM public.welfare_request_member_arrears_payments AS arp
            JOIN public.welfare_requests AS wr
                ON wr.id = arp.request_id
            JOIN public.members AS m
                ON m.member_id = arp.member_id
            ORDER BY arp.created_at DESC, arp.id DESC;
            """
        )
        welfare_arrears_payment_rows = cursor.fetchall()

        return {
            "subscriptions": subscriptions,
            "loans": loans,
            "sharing": sharing,
            "welfare": welfare,
            "welfare_member_balances": welfare_member_balances,
            "subscription_rows": subscription_rows,
            "subscription_proofs": subscription_proofs,
            "loan_rows": loan_rows,
            "loan_repayment_rows": loan_repayment_rows,
            "sharing_rows": sharing_rows,
            "sharing_withdrawal_rows": sharing_withdrawal_rows,
            "welfare_requests": welfare_requests,
            "welfare_contributors": welfare_contributors,
            "welfare_disbursement_rows": welfare_disbursement_rows,
            "welfare_contribution_rows": welfare_contribution_rows,
            "welfare_arrears_payment_rows": welfare_arrears_payment_rows,
        }


def fetch_member_financial_summary() -> Sequence[Mapping[str, Any]]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                members.member_id,
                members.full_name,
                COALESCE(subscriptions.total_contributions, 0)
                    AS total_contributions,
                COALESCE(welfare_contributions.total_welfare_contributions, 0)
                    AS total_welfare_contributions,
                COALESCE(welfare_balances.welfare_balance, 0)
                    AS current_welfare_balance,
                COALESCE(payouts.remaining_savings, 0) AS current_savings,
                COALESCE(payouts.disbursed_amount, 0) AS total_paid_out,
                COALESCE(payouts.available_payout, 0) AS available_payout
            FROM public.members AS members
            LEFT JOIN (
                SELECT
                    member_id,
                    SUM(amount_paid) AS total_contributions
                FROM public.subscriptions
                WHERE LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                GROUP BY member_id
            ) AS subscriptions
                ON subscriptions.member_id = members.member_id
            LEFT JOIN (
                SELECT member_id, SUM(amount) AS total_welfare_contributions
                FROM public.member_welfare_contributions
                GROUP BY member_id
            ) AS welfare_contributions
                ON welfare_contributions.member_id = members.member_id
            LEFT JOIN public.member_welfare_balances AS welfare_balances
                ON welfare_balances.member_id = members.member_id
            LEFT JOIN public.sharing_member_payouts AS payouts
                ON payouts.member_id = members.member_id
            ORDER BY members.full_name, members.member_id;
            """
        )
        return cursor.fetchall()
