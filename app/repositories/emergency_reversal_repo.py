from collections.abc import Mapping, Sequence
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any

from app.database import get_db
from app.repositories.financial_action_lock import acquire_financial_action_lock

REVERSAL_WINDOW = timedelta(hours=24)


def _allocate_refund(
    amount: Decimal,
    funding_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for row in funding_rows:
        for field in (
            "welfare_amount",
            "savings_amount",
            "arrears_amount",
        ):
            cents = int(Decimal(str(row[field] or 0)) * 100)
            if cents > 0:
                candidates.append(
                    {
                        "member_id": row["member_id"],
                        "account": field,
                        "weight_cents": cents,
                    }
                )

    total_weight = sum(item["weight_cents"] for item in candidates)
    amount_cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_FLOOR))
    if not candidates or amount_cents <= 0 or amount_cents > total_weight:
        return []

    remainder_rows = []
    allocated_cents = 0
    for item in candidates:
        base, remainder = divmod(amount_cents * item["weight_cents"], total_weight)
        item["returned_cents"] = base
        allocated_cents += base
        remainder_rows.append(
            (remainder, item["member_id"], item["account"], item)
        )

    remaining_cents = amount_cents - allocated_cents
    remainder_rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    for _, _, _, item in remainder_rows[:remaining_cents]:
        item["returned_cents"] += 1

    allocations_by_member = {}
    account_fields = {
        "welfare_amount": "welfare_amount_returned",
        "savings_amount": "savings_amount_returned",
        "arrears_amount": "arrears_amount_returned",
    }
    for item in candidates:
        member_allocation = allocations_by_member.setdefault(
            item["member_id"],
            {
                "member_id": item["member_id"],
                "welfare_amount_returned": Decimal("0"),
                "savings_amount_returned": Decimal("0"),
                "arrears_amount_returned": Decimal("0"),
            },
        )
        member_allocation[account_fields[item["account"]]] = (
            Decimal(item["returned_cents"]) / Decimal("100")
        )

    return [
        allocation
        for allocation in allocations_by_member.values()
        if (
            allocation["welfare_amount_returned"]
            + allocation["savings_amount_returned"]
            + allocation["arrears_amount_returned"]
        ) > 0
    ]


def _latest_action(cursor: Any) -> dict | None:
    cursor.execute(
        """
        SELECT
            action_type, action_id, member_id, full_name, amount,
            occurred_at, timestamp_verified, is_reversed, action_status,
            related_activity_count, case_number, checked_at
        FROM (
            SELECT
                'loan_approval'::text AS action_type,
                loan.loan_id::bigint AS action_id,
                loan.member_id,
                member.full_name,
                loan.amount_requested AS amount,
                CASE
                    WHEN loan.approved_at IS NOT NULL THEN loan.approved_at
                    ELSE loan.approved_date::timestamp
                         + INTERVAL '1 day' - INTERVAL '1 microsecond'
                END AS occurred_at,
                loan.approved_at IS NOT NULL AS timestamp_verified,
                reversal.id IS NOT NULL AS is_reversed,
                loan.status AS action_status,
                (
                    SELECT COUNT(*)
                    FROM public.loan_repayments repayments
                    WHERE repayments.loan_id = loan.loan_id
                ) + (
                    SELECT COUNT(*)
                    FROM public.audit_logs repayment_audits
                    WHERE repayment_audits.entity_type = 'loan_repayment'
                      AND repayment_audits.entity_id = loan.loan_id::text
                      AND repayment_audits.action
                          = 'treasurer_loan_installment_recorded'
                ) AS related_activity_count,
                NULL::text AS case_number,
                clock_timestamp()::timestamp AS checked_at
            FROM public.loans loan
            JOIN public.members member ON member.member_id = loan.member_id
            LEFT JOIN public.loan_approval_reversals reversal
                ON reversal.loan_id = loan.loan_id
            LEFT JOIN public.historical_loan_imports historical_import
                ON historical_import.loan_id = loan.loan_id
            WHERE LOWER(BTRIM(COALESCE(loan.status, '')))
                NOT IN ('pending', 'rejected')
              AND loan.approved_date IS NOT NULL
              AND historical_import.loan_id IS NULL

            UNION ALL

            SELECT
                'welfare_disbursement'::text AS action_type,
                disbursement.id AS action_id,
                request.member_id,
                request.member_name AS full_name,
                disbursement.amount,
                disbursement.disbursed_at AS occurred_at,
                TRUE AS timestamp_verified,
                reversal.id IS NOT NULL AS is_reversed,
                request.current_stage AS action_status,
                (
                    SELECT COUNT(*)
                    FROM public.welfare_request_disbursements later
                    WHERE later.request_id = disbursement.request_id
                      AND (
                          later.disbursed_at > disbursement.disbursed_at
                          OR (
                              later.disbursed_at = disbursement.disbursed_at
                              AND later.id > disbursement.id
                          )
                      )
                ) + (
                    SELECT COUNT(*)
                    FROM public.welfare_request_member_arrears_payments arrears
                    WHERE arrears.request_id = disbursement.request_id
                      AND arrears.created_at > disbursement.disbursed_at
                ) + (
                    SELECT COUNT(*)
                    FROM public.welfare_payments legacy
                    WHERE legacy.request_id = disbursement.request_id
                ) AS related_activity_count,
                request.case_number,
                clock_timestamp()::timestamp AS checked_at
            FROM public.welfare_request_disbursements disbursement
            JOIN public.welfare_requests request
                ON request.id = disbursement.request_id
            LEFT JOIN public.welfare_disbursement_reversals reversal
                ON reversal.disbursement_id = disbursement.id
            WHERE disbursement.amount > 0
        ) actions
        ORDER BY occurred_at DESC, action_type ASC, action_id DESC
        LIMIT 1;
        """
    )
    return cursor.fetchone()


def _blocked_reason(action: dict, now) -> str | None:
    if action["occurred_at"] > now:
        return "The recorded action time is invalid; contact the system administrator."
    if now - action["occurred_at"] >= REVERSAL_WINDOW:
        return "The 24-hour emergency reversal window has expired."
    if not action["timestamp_verified"]:
        return "The exact approval time is unavailable, so the 24-hour limit cannot be verified."
    if action["is_reversed"]:
        return "The latest action has already been reversed."
    if action["related_activity_count"]:
        return "Later related financial activity exists; this action cannot be safely reversed."
    if (
        action["action_type"] == "loan_approval"
        and str(action["action_status"] or "").strip().casefold() != "approved"
    ):
        return "The loan is no longer in its original approved state."
    if (
        action["action_type"] == "welfare_disbursement"
        and action["action_status"] not in {"Disbursed", "Partially Disbursed"}
    ):
        return "The welfare claim has changed since this disbursement."
    return None


def get_latest_emergency_action() -> dict | None:
    with get_db() as cursor:
        action = _latest_action(cursor)
        if not action:
            return None
        action["blocked_reason"] = _blocked_reason(action, action["checked_at"])
        action["can_reverse"] = action["blocked_reason"] is None
        action["amount"] = float(action["amount"])
        action["action_label"] = (
            "Loan approval"
            if action["action_type"] == "loan_approval"
            else "Welfare disbursement"
        )
        return action


def reverse_latest_emergency_action(
    action_type: str,
    action_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
    funds_received: bool,
) -> dict:
    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        action = _latest_action(cursor)
        if not action:
            return {"error": "no_reversible_action"}
        if action["action_type"] != action_type or action["action_id"] != action_id:
            return {"error": "action_is_no_longer_latest"}

        blocked_reason = _blocked_reason(action, action["checked_at"])
        if blocked_reason:
            return {"error": "action_not_reversible", "message": blocked_reason}
        if not funds_received:
            return {"error": "funds_not_confirmed"}
        if not reason.strip():
            return {"error": "reason_required"}

        if action_type == "loan_approval":
            cursor.execute(
                """
                SELECT loan_id, member_id, status, amount_requested,
                       approved_at, approved_date
                FROM public.loans
                WHERE loan_id = %s
                FOR UPDATE;
                """,
                (action_id,),
            )
            loan = cursor.fetchone()
            if not loan:
                return {"error": "action_is_no_longer_latest"}
            if (
                loan["approved_at"] != action["occurred_at"]
                or str(loan["status"] or "").strip().casefold() != "approved"
            ):
                return {"error": "action_is_no_longer_latest"}
            cursor.execute(
                """
                SELECT COUNT(*) AS repayment_count
                FROM public.loan_repayments
                WHERE loan_id = %s;
                """,
                (action_id,),
            )
            repayment_count = cursor.fetchone()
            if repayment_count is None:
                raise RuntimeError("Loan repayment check returned no result.")
            if repayment_count["repayment_count"]:
                return {"error": "action_not_reversible", "message":
                        "A loan repayment was recorded; this loan cannot be reversed."}
            amount = Decimal(str(loan["amount_requested"]))
            cursor.execute(
                """
                INSERT INTO public.loan_approval_reversals (
                    loan_id, amount_returned, reason, actor_name, actor_role,
                    returned_at
                )
                VALUES (%s, %s, %s, %s, %s, clock_timestamp()::timestamp);
                """,
                (action_id, amount, reason.strip(), actor_name, actor_role),
            )
            cursor.execute(
                """
                UPDATE public.loans
                SET status = 'Reversed',
                    interest_accumulated = 0,
                    outstanding_balance = 0,
                    total_interest_collected = 0
                WHERE loan_id = %s
                  AND LOWER(BTRIM(COALESCE(status, ''))) = 'approved'
                RETURNING loan_id;
                """,
                (action_id,),
            )
            if not cursor.fetchone():
                raise ValueError(
                    "Loan status changed during the emergency reversal; transaction rolled back."
                )
            previous_value = "Approved"
            new_value = "Reversed"
            entity_type = "loan"
            details = (
                f"Emergency reversal of approved loan #{action_id}. "
                f"UGX {amount:,.2f} principal was physically received back into "
                f"group working capital. Reason: {reason.strip()}"
            )
            member_id = loan["member_id"]
            case_number = None
            action_name = "emergency_loan_approval_reversed"
            entity_id = str(action_id)
        else:
            cursor.execute(
                """
                SELECT
                    disbursement.id, disbursement.request_id,
                    disbursement.amount, disbursement.target_amount,
                    request.member_id, request.case_number,
                    request.current_stage
                FROM public.welfare_request_disbursements disbursement
                JOIN public.welfare_requests request
                    ON request.id = disbursement.request_id
                WHERE disbursement.id = %s
                FOR UPDATE OF disbursement, request;
                """,
                (action_id,),
            )
            disbursement = cursor.fetchone()
            if not disbursement:
                return {"error": "action_is_no_longer_latest"}
            if disbursement["current_stage"] not in {
                "Disbursed",
                "Partially Disbursed",
            }:
                return {"error": "action_is_no_longer_latest"}
            amount = Decimal(str(disbursement["amount"]))
            cursor.execute(
                """
                SELECT
                    contributions.member_id,
                    contributions.welfare_amount,
                    contributions.savings_amount,
                    COALESCE(arrears.amount, 0) AS arrears_amount
                FROM public.welfare_request_member_contributions contributions
                LEFT JOIN (
                    SELECT request_id, member_id, SUM(amount) AS amount
                    FROM public.welfare_request_member_arrears_payments
                    WHERE request_id = %s
                    GROUP BY request_id, member_id
                ) arrears USING (request_id, member_id)
                WHERE contributions.request_id = %s
                ORDER BY contributions.member_id;
                """,
                (disbursement["request_id"], disbursement["request_id"]),
            )
            funding_rows = cursor.fetchall()
            allocations = _allocate_refund(amount, funding_rows)
            if not allocations:
                return {
                    "error": "member_funding_not_found",
                    "message": (
                        "Individual member funding records are unavailable or do not "
                        "cover this disbursement; no accounts were changed."
                    ),
                }

            member_ids = [allocation["member_id"] for allocation in allocations]
            cursor.execute(
                """
                SELECT
                    members.member_id,
                    COALESCE(welfare.welfare_balance, 0) AS welfare_balance,
                    COALESCE(payouts.remaining_savings, 0) AS savings_balance
                FROM public.members members
                LEFT JOIN public.member_welfare_balances welfare
                    ON welfare.member_id = members.member_id
                LEFT JOIN public.sharing_member_payouts payouts
                    ON payouts.member_id = members.member_id
                WHERE members.member_id = ANY(%s)
                FOR UPDATE OF members;
                """,
                (member_ids,),
            )
            account_balances = {
                row["member_id"]: row for row in cursor.fetchall()
            }
            if len(account_balances) != len(member_ids):
                raise RuntimeError(
                    "Could not load every member account before recording its refund."
                )
            cursor.execute(
                """
                INSERT INTO public.welfare_disbursement_reversals (
                    disbursement_id, request_id, amount_returned, reason,
                    actor_name, actor_role, returned_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp()::timestamp)
                RETURNING id;
                """,
                (
                    action_id,
                    disbursement["request_id"],
                    amount,
                    reason.strip(),
                    actor_name,
                    actor_role,
                ),
            )
            reversal_row = cursor.fetchone()
            if not reversal_row:
                raise RuntimeError("The welfare reversal ledger entry was not created.")
            reversal_id = reversal_row["id"]
            cursor.executemany(
                """
                INSERT INTO public.welfare_disbursement_reversal_allocations (
                    reversal_id, request_id, member_id,
                    welfare_amount_returned, savings_amount_returned,
                    arrears_amount_returned, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp()::timestamp);
                """,
                [
                    (
                        reversal_id,
                        disbursement["request_id"],
                        allocation["member_id"],
                        allocation["welfare_amount_returned"],
                        allocation["savings_amount_returned"],
                        allocation["arrears_amount_returned"],
                    )
                    for allocation in allocations
                ],
            )
            for allocation in allocations:
                member_id_for_credit = allocation["member_id"]
                restored_welfare = (
                    allocation["welfare_amount_returned"]
                    + allocation["arrears_amount_returned"]
                )
                restored_savings = allocation["savings_amount_returned"]
                previous = account_balances[member_id_for_credit]
                details = (
                    f"Emergency welfare disbursement reversal for case "
                    f"{disbursement['case_number']}: restored UGX "
                    f"{restored_welfare:,.2f} to the member welfare account "
                    f"(including arrears paid) and UGX {restored_savings:,.2f} "
                    f"to savings. Reason: {reason.strip()}"
                )
                cursor.execute(
                    """
                    INSERT INTO public.audit_logs (
                        entity_type, entity_id, action, actor_name, actor_role,
                        details, previous_value, new_value, created_at
                    )
                    VALUES (
                        'member_welfare_account', %s,
                        'emergency_welfare_funds_returned_to_member',
                        %s, %s, %s, %s, %s, clock_timestamp()::timestamp
                    );
                    """,
                    (
                        str(member_id_for_credit),
                        actor_name,
                        actor_role,
                        details,
                        (
                            f"Welfare UGX {Decimal(str(previous['welfare_balance'])):,.2f}; "
                            f"savings UGX {Decimal(str(previous['savings_balance'])):,.2f}"
                        ),
                        (
                            f"Welfare UGX "
                            f"{Decimal(str(previous['welfare_balance'])) + restored_welfare:,.2f}; "
                            f"savings UGX "
                            f"{Decimal(str(previous['savings_balance'])) + restored_savings:,.2f}"
                        ),
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
                        'Member', %s, 'Welfare funds returned to your accounts',
                        %s, FALSE, 'Finance reversal', 'Welfare Support',
                        'High', '/api/welfare/view', 'Delivered',
                        clock_timestamp()::timestamp
                    );
                    """,
                    (member_id_for_credit, details),
                )
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(disbursements.amount), 0)
                    - COALESCE(SUM(reversals.amount_returned), 0)
                    + COALESCE((
                        SELECT SUM(legacy.amount)
                        FROM public.welfare_payments legacy
                        WHERE legacy.request_id = %s
                    ), 0) AS net_disbursed
                FROM public.welfare_request_disbursements disbursements
                LEFT JOIN public.welfare_disbursement_reversals reversals
                    ON reversals.disbursement_id = disbursements.id
                WHERE disbursements.request_id = %s;
                """,
                (disbursement["request_id"], disbursement["request_id"]),
            )
            disbursement_totals = cursor.fetchone()
            if disbursement_totals is None:
                raise RuntimeError("Welfare disbursement totals returned no result.")
            net_disbursed = Decimal(str(disbursement_totals["net_disbursed"]))
            target_amount = Decimal(str(disbursement["target_amount"]))
            if net_disbursed >= target_amount:
                new_status, new_stage = "Paid", "Disbursed"
            elif net_disbursed > 0:
                new_status, new_stage = "Partially Paid", "Partially Disbursed"
            else:
                new_status, new_stage = "Approved", "Executive Approved"
            cursor.execute(
                """
                UPDATE public.welfare_requests
                SET status = %s, current_stage = %s, updated_at = NOW()
                WHERE id = %s
                  AND current_stage IN ('Disbursed', 'Partially Disbursed')
                RETURNING id;
                """,
                (new_status, new_stage, disbursement["request_id"]),
            )
            if not cursor.fetchone():
                raise ValueError(
                    "Welfare claim changed during the emergency reversal; transaction rolled back."
                )
            previous_value = disbursement["current_stage"]
            new_value = new_stage
            entity_type = "welfare_request"
            member_id = disbursement["member_id"]
            case_number = disbursement["case_number"]
            action_name = "emergency_welfare_disbursement_reversed"
            entity_id = str(disbursement["request_id"])
            details = (
                f"Emergency reversal of welfare disbursement #{action_id} "
                f"for case {case_number}. UGX {amount:,.2f} was physically "
                f"received back into the welfare fund and allocated to "
                f"{len(allocations)} member account(s) by their original funding "
                f"shares. Reason: {reason.strip()}"
            )

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp()::timestamp);
            """,
            (
                entity_type,
                entity_id,
                action_name,
                actor_name,
                actor_role,
                details,
                previous_value,
                new_value,
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
                'Member', %s, %s, %s, FALSE, 'Finance reversal',
                'Executive Action Center', 'High', %s, 'Delivered',
                clock_timestamp()::timestamp
            );
            """,
            (
                member_id,
                "Financial action reversed",
                details,
                "/api/loans/view" if action_type == "loan_approval" else "/api/welfare/view",
            ),
        )
        return {
            "status": "success",
            "action_type": action_type,
            "action_id": action_id,
            "amount_returned": float(amount),
            "message": (
                (
                    f"Loan approval reversed. UGX {amount:,.2f} was recorded as "
                    "returned to group working capital. "
                    if action_type == "loan_approval"
                    else f"Welfare disbursement reversed. UGX {amount:,.2f} was "
                    "returned to the welfare fund and allocated back across the "
                    "members' original welfare, savings, and arrears funding accounts. "
                )
                + "The reversal and reason are in the audit log."
            ),
        }
