# app/repositories/loan_repo.py
from datetime import date, datetime
from decimal import Decimal
import logging

from app.database import get_db
from app.repositories.financial_action_lock import acquire_financial_action_lock
from app.membership_rules import is_probationary_member
from app.loan_interest import (
    MONEY_PRECISION,
    MONTHLY_LOAN_INTEREST_RATE,
    calculate_monthly_loan_interest,
    next_monthly_interest_due_date,
)
from app.subscription_rules import (
    INACTIVE_ARREARS_THRESHOLD,
    calculate_subscription_arrears,
)

logger = logging.getLogger(__name__)

def get_member_status(member_str_id: str):
    """Fetches a member's account status and membership details."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT member_id, status, role, override_status
            FROM members
            WHERE member_id = %s;
            """,
            (member_str_id,)
        )
        return cursor.fetchone()

def get_loans_by_member(member_str_id: str):
    """Fetches all loan records for a specific member from Neon."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT loan_id AS id, member_id, amount_requested, interest_accumulated, 
                   outstanding_balance, status, applied_date AS created_at, 
                   approved_date, purpose, mobile_money_number, rejection_reason,
                   last_interest_applied_date
            FROM loans
            WHERE member_id = %s
            ORDER BY applied_date DESC;
            """,
            (member_str_id,)
        )
        return cursor.fetchall()

def submit_loan_application_if_eligible(
    member_str_id: str,
    amount: float,
    purpose: str,
    mobile_money_number: str,
):
    """Serializes applications per member and enforces the one-active-loan rule."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                status,
                override_status,
                COALESCE(joined_date, join_date, CURRENT_DATE) AS joined_date
            FROM members
            WHERE member_id = %s
            FOR UPDATE;
            """,
            (member_str_id,),
        )
        member = cursor.fetchone()
        if member is None:
            return {"error": "member_not_found"}
        account_status = (member.get("status") or "").strip()
        if account_status.casefold() == "suspended":
            return {
                "error": "member_account_inactive",
                "account_status": account_status,
            }
        if is_probationary_member(member.get("joined_date")):
            return {"error": "member_on_probation"}

        cursor.execute(
            """
            SELECT
                CURRENT_DATE AS evaluated_on,
                COALESCE(SUM(amount_paid), 0) AS current_year_contributions
            FROM public.subscriptions
            WHERE member_id = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
              AND billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
              AND billing_month < (
                  DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
              )::date;
            """,
            (member_str_id,),
        )
        contributions = cursor.fetchone()
        if contributions is None:
            raise RuntimeError("Subscription eligibility query returned no result.")
        arrears, _ = calculate_subscription_arrears(
            float(contributions["current_year_contributions"] or 0),
            contributions["evaluated_on"] or date.today(),
        )
        override_status = (member.get("override_status") or "").strip().casefold()
        if override_status and not override_status.endswith("/ active"):
            return {
                "error": "member_classified_inactive",
                "arrears": arrears,
                "override_status": member["override_status"],
            }
        if not override_status and arrears > INACTIVE_ARREARS_THRESHOLD:
            return {
                "error": "member_classified_inactive",
                "arrears": arrears,
            }

        cursor.execute(
            """
            SELECT loan_id, status
            FROM loans
            WHERE member_id = %s
              AND LOWER(BTRIM(COALESCE(status, '')))
                    IN ('pending', 'approved', 'active')
            LIMIT 1;
            """,
            (member_str_id,),
        )
        existing_loan = cursor.fetchone()
        if existing_loan:
            return {
                "error": "existing_loan",
                "loan_id": existing_loan["loan_id"],
                "loan_status": existing_loan["status"],
            }

        cursor.execute(
            """
            INSERT INTO loans (
                member_id, amount_requested, purpose, mobile_money_number,
                outstanding_balance, status, applied_date
            )
            VALUES (%s, %s, %s, %s, %s, 'Pending', CURRENT_DATE)
            RETURNING loan_id AS id, status;
            """,
            (member_str_id, amount, purpose, mobile_money_number, 0.0),
        )
        application = cursor.fetchone()
        if application is None:
            raise RuntimeError("Loan application insert returned no confirmation.")
        return application

def get_pending_loans():
    """Fetches all pending loan applications for executive review."""
    with get_db() as cursor:
        cursor.execute(
            """
            WITH member_savings_totals AS (
                SELECT COALESCE(SUM(remaining_savings), 0) AS total_member_savings
                FROM public.sharing_member_payouts
            ),
            principal_repayments AS (
                SELECT loan_id, SUM(COALESCE(principal_paid, 0)) AS principal_paid
                FROM public.loan_repayments
                GROUP BY loan_id
            ),
            loan_totals AS (
                SELECT COALESCE(
                    SUM(
                        GREATEST(
                            COALESCE(loans.amount_requested, 0)
                                - COALESCE(principal_repayments.principal_paid, 0),
                            0
                        )
                    ),
                    0
                ) AS unpaid_loan_principal
                FROM public.loans loans
                LEFT JOIN principal_repayments
                    ON principal_repayments.loan_id = loans.loan_id
                WHERE LOWER(BTRIM(COALESCE(loans.status, ''))) IN ('approved', 'active')
            )
            SELECT
                l.loan_id AS id,
                l.member_id,
                l.amount_requested,
                l.purpose,
                l.mobile_money_number,
                l.applied_date AS created_at,
                l.status,
                COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                    - COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0)
                    AS available_working_capital,
                CASE
                    WHEN l.amount_requested > (
                        COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                        - COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0)
                    )
                    THEN TRUE
                    ELSE FALSE
                END AS is_working_capital_exceeded,
                CASE
                    WHEN l.amount_requested > (
                        COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                        - COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0)
                    )
                    THEN CONCAT(
                        'Warning: request UGX ',
                        TO_CHAR(l.amount_requested, 'FM999,999,999,999.00'),
                        ' exceeds the available working capital of UGX ',
                        TO_CHAR(
                            COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                            - COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0),
                            'FM999,999,999,999.00'
                        ),
                        '. Recommend a smaller amount or an alternative funding option; this request cannot be approved as submitted.'
                    )
                    ELSE NULL
                END AS working_capital_warning
            FROM loans l
            WHERE LOWER(BTRIM(COALESCE(l.status, ''))) = 'pending'
            ORDER BY l.applied_date ASC;
            """
        )
        return cursor.fetchall()

def get_working_capital_snapshot():
    """Returns the available group working capital available for new borrowing."""
    with get_db() as cursor:
        cursor.execute(
            """
            WITH member_savings_totals AS (
                SELECT COALESCE(SUM(remaining_savings), 0) AS total_member_savings
                FROM public.sharing_member_payouts
            ),
            principal_repayments AS (
                SELECT loan_id, SUM(COALESCE(principal_paid, 0)) AS principal_paid
                FROM public.loan_repayments
                GROUP BY loan_id
            ),
            loan_totals AS (
                SELECT COALESCE(
                    SUM(
                        GREATEST(
                            COALESCE(loans.amount_requested, 0)
                                - COALESCE(principal_repayments.principal_paid, 0),
                            0
                        )
                    ),
                    0
                ) AS unpaid_loan_principal
                FROM public.loans loans
                LEFT JOIN principal_repayments
                    ON principal_repayments.loan_id = loans.loan_id
                WHERE LOWER(BTRIM(COALESCE(loans.status, ''))) IN ('approved', 'active')
            )
            SELECT
                COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                    - COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0)
                    AS available_working_capital,
                COALESCE((SELECT total_member_savings FROM member_savings_totals), 0)
                    AS total_member_savings,
                COALESCE((SELECT unpaid_loan_principal FROM loan_totals), 0)
                    AS unpaid_loan_principal;
            """
        )
        return cursor.fetchone() or {
            "available_working_capital": 0,
            "total_member_savings": 0,
            "unpaid_loan_principal": 0,
        }

def approve_loan_in_db(loan_id: int, executive_name: str):
    """
    Approves a loan, sets initial 10% monthly interest on approval date,
    and calculates the initial outstanding balance.
    """
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT amount_requested
            FROM loans
            WHERE loan_id = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) = 'pending'
            FOR UPDATE;
            """,
            (loan_id,),
        )
        loan = cursor.fetchone()
        if not loan:
            return None

        working_capital = get_working_capital_snapshot()
        available_working_capital = float(working_capital["available_working_capital"] or 0)
        principal = Decimal(str(loan["amount_requested"]))
        if principal > Decimal(str(available_working_capital)):
            raise ValueError(
                f"Loan request amount UGX {principal:,.0f} exceeds the available working capital of UGX {available_working_capital:,.0f}. "
                "Recommend a smaller amount or an alternative funding option; this request cannot be approved as submitted."
            )

        initial_interest = calculate_monthly_loan_interest(principal)
        initial_balance = principal + initial_interest
        
        cursor.execute(
            """
            UPDATE loans
            SET status = 'Approved', 
                approved_date = CURRENT_DATE,
                approved_at = clock_timestamp()::timestamp,
                last_interest_applied_date = CURRENT_DATE,
                interest_accumulated = %s,
                outstanding_balance = %s,
                approved_by = %s,
                rejection_reason = NULL
            WHERE loan_id = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) = 'pending'
            RETURNING loan_id AS id, status;
            """,
            (initial_interest, initial_balance, executive_name, loan_id)
        )
        approved_loan = cursor.fetchone()
        if not approved_loan:
            return None

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            SELECT
                'loan', loan_id::text, 'loan_approved_and_disbursed',
                %s, 'Executive',
                %s, 'Pending', 'Approved', NOW()
            FROM public.loans
            WHERE loan_id = %s;
            """,
            (
                executive_name,
                f"Loan #{loan_id} approved and treated as disbursed. "
                f"Principal UGX {principal:,.2f}; initial interest "
                f"UGX {initial_interest:,.2f}.",
                loan_id,
            ),
        )
        return approved_loan


def apply_due_loan_interest() -> dict:
    """Apply each due monthly interest installment once to every running loan."""
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute("SELECT CURRENT_DATE AS today;")
        date_row = cursor.fetchone()
        if date_row is None:
            raise RuntimeError("Could not determine the database date for loan interest.")
        today = date_row["today"]

        cursor.execute(
            """
            WITH repayment_totals AS (
                SELECT repayment.loan_id,
                       SUM(COALESCE(repayment.principal_paid, 0)) AS principal_paid
                FROM public.loan_repayments AS repayment
                WHERE repayment.loan_id IN (
                    SELECT loan.loan_id
                    FROM public.loans AS loan
                    WHERE LOWER(BTRIM(COALESCE(loan.status, '')))
                              IN ('approved', 'active')
                      AND COALESCE(
                            loan.last_interest_applied_date,
                            loan.approved_date
                          ) IS NOT NULL
                      AND (
                            DATE_TRUNC(
                                'month',
                                COALESCE(
                                    loan.last_interest_applied_date,
                                    loan.approved_date
                                )
                            )
                            + INTERVAL '1 month'
                            + (
                                LEAST(
                                    EXTRACT(
                                        DAY FROM COALESCE(
                                            loan.last_interest_applied_date,
                                            loan.approved_date
                                        )
                                    )::integer,
                                    28
                                ) - 1
                            ) * INTERVAL '1 day'
                          )::date <= CURRENT_DATE
                )
                GROUP BY loan_id
            )
            SELECT
                loan.loan_id,
                loan.member_id,
                loan.amount_requested,
                loan.outstanding_balance,
                loan.interest_accumulated,
                COALESCE(loan.last_interest_applied_date, loan.approved_date)
                    AS last_interest_date,
                COALESCE(repayment_totals.principal_paid, 0) AS principal_paid
            FROM public.loans AS loan
            LEFT JOIN repayment_totals
                ON repayment_totals.loan_id = loan.loan_id
            WHERE LOWER(BTRIM(COALESCE(loan.status, ''))) IN ('approved', 'active')
              AND COALESCE(loan.last_interest_applied_date, loan.approved_date)
                    IS NOT NULL
              AND (
                    DATE_TRUNC(
                        'month',
                        COALESCE(
                            loan.last_interest_applied_date,
                            loan.approved_date
                        )
                    )
                    + INTERVAL '1 month'
                    + (
                        LEAST(
                            EXTRACT(
                                DAY FROM COALESCE(
                                    loan.last_interest_applied_date,
                                    loan.approved_date
                                )
                            )::integer,
                            28
                        ) - 1
                    ) * INTERVAL '1 day'
                  )::date <= CURRENT_DATE
            ORDER BY loan.loan_id
            FOR UPDATE OF loan;
            """
        )
        loans = cursor.fetchall()
        accrued_loan_count = 0
        installment_count = 0
        total_interest_added = Decimal("0")

        for loan in loans:
            last_interest_date = loan["last_interest_date"]
            if isinstance(last_interest_date, datetime):
                last_interest_date = last_interest_date.date()
            elif isinstance(last_interest_date, str):
                last_interest_date = date.fromisoformat(last_interest_date[:10])

            principal_remaining = max(
                Decimal(str(loan["amount_requested"] or 0))
                - Decimal(str(loan["principal_paid"] or 0)),
                Decimal("0"),
            )
            outstanding_balance = Decimal(str(loan["outstanding_balance"] or 0))
            interest_accumulated = Decimal(str(loan["interest_accumulated"] or 0))
            loan_interest_added = Decimal("0")
            loan_installments = 0
            due_date = next_monthly_interest_due_date(last_interest_date)

            while due_date <= today:
                interest = calculate_monthly_loan_interest(principal_remaining)
                loan_interest_added += interest
                loan_installments += 1
                last_interest_date = due_date
                due_date = next_monthly_interest_due_date(last_interest_date)

            if loan_installments == 0:
                continue

            new_balance = outstanding_balance + loan_interest_added
            new_interest_accumulated = interest_accumulated + loan_interest_added
            cursor.execute(
                """
                UPDATE public.loans
                SET outstanding_balance = %s,
                    interest_accumulated = %s,
                    last_interest_applied_date = %s
                WHERE loan_id = %s
                  AND LOWER(BTRIM(COALESCE(status, ''))) IN ('approved', 'active')
                RETURNING loan_id;
                """,
                (
                    new_balance,
                    new_interest_accumulated,
                    last_interest_date,
                    loan["loan_id"],
                ),
            )
            if not cursor.fetchone():
                raise RuntimeError(
                    f"Loan {loan['loan_id']} changed before interest could be applied."
                )

            if loan_interest_added > 0:
                details = (
                    f"Automatically accrued {loan_installments} monthly interest "
                    f"installment(s) at "
                    f"{MONTHLY_LOAN_INTEREST_RATE:.0%} of remaining principal "
                    "(no compounding). "
                    f"Principal UGX {principal_remaining:,.2f}; interest added "
                    f"UGX {loan_interest_added:,.2f}; next interest date "
                    f"{last_interest_date.isoformat()}."
                )
                cursor.execute(
                    """
                    INSERT INTO public.audit_logs (
                        entity_type, entity_id, action, actor_name, actor_role,
                        details, previous_value, new_value, created_at
                    )
                    VALUES (
                        'loan', %s, 'monthly_loan_interest_accrued',
                        'System', 'System', %s, %s, %s, NOW()
                    );
                    """,
                    (
                        str(loan["loan_id"]),
                        details,
                        str(outstanding_balance),
                        str(new_balance),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO public.notifications (
                        recipient_type, recipient_id, title, message, is_read,
                        category, module_name, priority, action_link,
                        delivery_status, created_at
                    )
                    VALUES (
                        'Member', %s, 'Monthly loan interest applied', %s, FALSE,
                        'Loans', 'Loan Account', 'Normal', '/api/loans/view',
                        'Delivered', NOW()
                    );
                    """,
                    (
                        loan["member_id"],
                        f"UGX {loan_interest_added:,.2f} interest was added to "
                        f"loan #{loan['loan_id']} for {loan_installments} due "
                        f"monthly installment(s). Interest is calculated only "
                        f"on remaining principal at "
                        f"{MONTHLY_LOAN_INTEREST_RATE:.0%}. New balance: "
                        f"UGX {new_balance:,.2f}.",
                    ),
                )

            accrued_loan_count += 1
            installment_count += loan_installments
            total_interest_added += loan_interest_added

        return {
            "loan_count": accrued_loan_count,
            "installment_count": installment_count,
            "interest_added": total_interest_added.quantize(MONEY_PRECISION),
        }

def reject_loan_in_db(
    loan_id: int,
    executive_name: str,
    rejection_reason: str,
):
    """Rejects a loan application."""
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE loans
            SET status = 'Rejected',
                approved_by = %s,
                rejection_reason = %s
            WHERE loan_id = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) = 'pending'
            RETURNING loan_id AS id, status, member_id;
            """,
            (executive_name, rejection_reason, loan_id)
        )
        rejected_loan = cursor.fetchone()
        if not rejected_loan:
            return None

        cursor.execute(
            """
            INSERT INTO public.notifications (
                recipient_type, recipient_id, title, message, is_read,
                category, module_name, priority, action_link,
                delivery_status, created_at
            )
            VALUES (
                'Member', %s, 'Loan application decision', %s, FALSE,
                'Loans', 'Loans', 'High', '/api/loans/view',
                'Delivered', NOW()
            );
            """,
            (
                rejected_loan["member_id"],
                f"Your loan application #{loan_id} was not approved. "
                f"Reason: {rejection_reason}",
            ),
        )
        return rejected_loan