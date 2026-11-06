from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.database import get_db
from app.membership_rules import is_probationary_member
from app.repositories.financial_action_lock import acquire_financial_action_lock
from app.welfare_rules import (
    allowed_relationships_for_category,
    is_eligible_beneficiary,
    normalize_family_relationship,
    normalize_welfare_category,
)

WELFARE_CONTRIBUTION_PER_MEMBER = Decimal("20000.00")


def _assess_member_welfare_contribution(
    welfare_balance: Decimal | float | int | str | None,
    savings_balance: Decimal | float | int | str | None,
) -> tuple[Decimal, Decimal, Decimal]:
    welfare_balance = max(
        Decimal(str(welfare_balance if welfare_balance is not None else 0)),
        Decimal("0"),
    )
    savings_balance = max(
        Decimal(str(savings_balance if savings_balance is not None else 0)),
        Decimal("0"),
    )
    welfare_amount = min(welfare_balance, WELFARE_CONTRIBUTION_PER_MEMBER)
    savings_amount = min(
        savings_balance,
        WELFARE_CONTRIBUTION_PER_MEMBER - welfare_amount,
    )
    outstanding_amount = (
        WELFARE_CONTRIBUTION_PER_MEMBER - welfare_amount - savings_amount
    )
    return welfare_amount, savings_amount, outstanding_amount


def get_member_welfare_eligibility(member_id: str) -> dict | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(m.joined_date, m.join_date, CURRENT_DATE) AS joined_date,
                COALESCE(balances.welfare_balance, 0) AS welfare_balance
            FROM public.members m
            LEFT JOIN public.member_welfare_balances balances
                ON balances.member_id = m.member_id
            WHERE m.member_id = %s;
            """,
            (member_id,),
        )
        return cursor.fetchone()


def get_welfare_claims_by_member(member_str_id: str):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                requests.id, requests.case_number, requests.member_id,
                requests.member_name, requests.support_category,
                requests.beneficiary_name, requests.beneficiary_relationship,
                requests.description, requests.evidence_file_url,
                requests.status, requests.current_stage, requests.created_at,
                COALESCE(disbursements.amount, 0) AS disbursed_amount
            FROM public.welfare_requests requests
            LEFT JOIN (
                SELECT request_id, SUM(amount) AS amount
                FROM (
                    SELECT
                        disbursements.request_id,
                        disbursements.amount - COALESCE(
                            reversals.amount_returned, 0
                        ) AS amount
                    FROM public.welfare_request_disbursements disbursements
                    LEFT JOIN public.welfare_disbursement_reversals reversals
                        ON reversals.disbursement_id = disbursements.id
                    UNION ALL
                    SELECT request_id, amount
                    FROM public.welfare_payments
                ) payments
                GROUP BY request_id
            ) disbursements ON disbursements.request_id = requests.id
            WHERE requests.member_id = %s
            ORDER BY requests.created_at DESC;
            """,
            (member_str_id,),
        )
        return cursor.fetchall()


def insert_welfare_claim(
    member_id: str,
    member_name: str,
    support_category: str,
    beneficiary_id: str,
    description: str,
    evidence_file_url: str,
    membership_status: str = "Active",
):
    case_number = f"WEL-{uuid4().hex[:6].upper()}"

    with get_db() as cursor:
        category = normalize_welfare_category(support_category)
        if category is None:
            return {"error": "invalid_support_category"}

        if beneficiary_id == "self":
            beneficiary_name = member_name
            beneficiary_relationship = "Member"
            relative_id = None
        else:
            try:
                relative_id = int(beneficiary_id)
            except (TypeError, ValueError):
                return {"error": "beneficiary_not_found"}
            cursor.execute(
                """
                SELECT id, relationship_type, full_legal_name, vital_status
                FROM public.family_registry
                WHERE id = %s AND member_id = %s
                FOR SHARE;
                """,
                (relative_id, member_id),
            )
            relative = cursor.fetchone()
            if relative is None:
                return {"error": "beneficiary_not_found"}
            if not is_eligible_beneficiary(category, relative):
                relationship = normalize_family_relationship(
                    str(relative.get("relationship_type") or "")
                )
                if relationship not in allowed_relationships_for_category(category):
                    return {"error": "beneficiary_relationship_ineligible"}
                return {"error": "beneficiary_vital_status_ineligible"}
            beneficiary_name = relative["full_legal_name"]
            beneficiary_relationship = relative["relationship_type"].strip()

        cursor.execute(
            """
            INSERT INTO public.welfare_requests (
                case_number, member_id, member_name, membership_status,
                request_date, support_category, description,
                evidence_file_url, status, current_stage, is_active, created_at,
                relative_id, beneficiary_name, beneficiary_relationship
            )
            VALUES (
                %s, %s, %s, %s, CURRENT_DATE, %s, %s, %s,
                'Pending', 'Submitted', TRUE, NOW(), %s, %s, %s
            )
            RETURNING id, case_number, status,
                      beneficiary_name, beneficiary_relationship;
            """,
            (
                case_number,
                member_id,
                member_name,
                membership_status,
                support_category,
                description,
                evidence_file_url,
                relative_id,
                beneficiary_name,
                beneficiary_relationship,
            ),
        )
        claim = cursor.fetchone()
        if claim is None:
            raise RuntimeError("Welfare claim insert returned no confirmation.")
        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'welfare_request', %s, 'welfare_claim_submitted',
                %s, 'Member', %s, '', 'Submitted', NOW()
            );
            """,
            (
                str(claim["id"]),
                member_name,
                f"{case_number} submitted under category {category} for "
                f"{beneficiary_relationship} {beneficiary_name}.",
            ),
        )
        return claim


def get_all_welfare_claims_for_staff():
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                requests.id, requests.case_number, requests.member_id,
                requests.member_name, requests.support_category,
                requests.beneficiary_name, requests.beneficiary_relationship,
                requests.description, requests.evidence_file_url,
                requests.status, requests.current_stage, requests.created_at,
                COALESCE(disbursements.amount, 0) AS disbursed_amount
            FROM public.welfare_requests requests
            LEFT JOIN (
                SELECT request_id, SUM(amount) AS amount
                FROM (
                    SELECT
                        disbursements.request_id,
                        disbursements.amount - COALESCE(
                            reversals.amount_returned, 0
                        ) AS amount
                    FROM public.welfare_request_disbursements disbursements
                    LEFT JOIN public.welfare_disbursement_reversals reversals
                        ON reversals.disbursement_id = disbursements.id
                    UNION ALL
                    SELECT request_id, amount
                    FROM public.welfare_payments
                ) payments
                GROUP BY request_id
            ) disbursements ON disbursements.request_id = requests.id
            ORDER BY requests.created_at ASC;
            """
        )
        return cursor.fetchall()


def update_welfare_claim_stage(
    claim_id: int,
    new_status: str,
    new_stage: str,
    role: str,
    actor_name: str,
    comment_text: str,
):
    role_key = role.strip().casefold()
    if role_key in {"welfare", "welfare officer", "treasurer"}:
        expected_stage = "Submitted"
        comment_field = "welfare_officer_comment" if role_key != "treasurer" else "treasurer_comment"
    elif role_key == "chairperson":
        expected_stage = "Under Review"
        comment_field = "chairperson_comment"
    else:
        return {"error": "role_not_allowed"}

    allowed_transition = (
        (role_key in {"welfare", "welfare officer", "treasurer"}
            and new_stage == "Under Review" and new_status == "Under Review")
        or (role_key == "chairperson"
            and new_stage == "Executive Approved" and new_status == "Approved")
        or (role_key == "chairperson"
            and new_stage == "Rejected" and new_status == "Rejected")
    )
    if not allowed_transition:
        return {"error": "transition_not_allowed"}

    with get_db() as cursor:
        cursor.execute(
            f"""
            UPDATE public.welfare_requests
            SET status = %s,
                current_stage = %s,
                {comment_field} = %s,
                updated_at = NOW()
            WHERE id = %s
              AND current_stage = %s
            RETURNING id, case_number, status, current_stage;
            """,
            (new_status, new_stage, comment_text, claim_id, expected_stage),
        )
        updated = cursor.fetchone()
        if not updated:
            cursor.execute(
                "SELECT id, current_stage FROM public.welfare_requests WHERE id = %s;",
                (claim_id,),
            )
            claim = cursor.fetchone()
            return {"error": "claim_not_found" if not claim else "invalid_current_stage"}

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'welfare_request', %s, 'welfare_stage_changed',
                %s, %s, %s, %s, %s, NOW()
            );
            """,
            (
                str(claim_id),
                actor_name,
                role,
                comment_text or f"Changed welfare stage to {new_stage}.",
                expected_stage,
                new_stage,
            ),
        )
        return updated


def disburse_welfare_claim(
    claim_id: int,
    actor_name: str,
    actor_role: str,
) -> dict:
    payment_reference = f"WEL-PAY-{uuid4().hex[:12].upper()}"

    with get_db() as cursor:
        acquire_financial_action_lock(cursor)
        cursor.execute(
            """
            SELECT id, case_number, member_id, member_name, support_category,
                   beneficiary_name, beneficiary_relationship,
                   status, current_stage, created_at
            FROM public.welfare_requests
            WHERE id = %s
            FOR UPDATE;
            """,
            (claim_id,),
        )
        claim = cursor.fetchone()
        if not claim:
            return {"error": "claim_not_found"}
        claim_created_at = claim["created_at"]
        if isinstance(claim_created_at, datetime):
            claim_created_on = claim_created_at.date()
        elif isinstance(claim_created_at, date):
            claim_created_on = claim_created_at
        else:
            raise RuntimeError("Welfare claim has no valid creation date.")
        if claim["current_stage"] not in {
            "Executive Approved",
            "Partially Disbursed",
            "Funding Shortfall",
        }:
            return {"error": "claim_not_approved"}
        cursor.execute(
            """
            SELECT COALESCE(SUM(
                disbursements.amount - COALESCE(reversals.amount_returned, 0)
            ), 0) AS amount
            FROM public.welfare_request_disbursements disbursements
            LEFT JOIN public.welfare_disbursement_reversals reversals
                ON reversals.disbursement_id = disbursements.id
            WHERE disbursements.request_id = %s;
            """,
            (claim_id,),
        )
        previous_disbursed = Decimal(str(cursor.fetchone()["amount"]))
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(amount), 0) AS amount
            FROM public.welfare_payments
            WHERE request_id = %s;
            """,
            (claim_id,),
        )
        legacy_disbursed = Decimal(str(cursor.fetchone()["amount"]))
        if claim["current_stage"] == "Executive Approved" and legacy_disbursed > 0:
            return {"error": "legacy_disbursement_exists"}
        previous_disbursed += legacy_disbursed

        cursor.execute(
            """
            SELECT
                member_id,
                full_name,
                COALESCE(joined_date, join_date, CURRENT_DATE) AS joined_date
            FROM public.members
            ORDER BY member_id
            FOR UPDATE;
            """
        )
        members = cursor.fetchall()
        if not members:
            return {"error": "no_registered_members"}

        cursor.execute(
            """
            SELECT COUNT(*) AS contribution_count
            FROM public.welfare_request_member_contributions
            WHERE request_id = %s;
            """,
            (claim_id,),
        )
        has_contribution_snapshot = cursor.fetchone()["contribution_count"] > 0

        cursor.execute(
            """
            SELECT
                members.member_id,
                members.full_name,
                COALESCE(members.joined_date, members.join_date, CURRENT_DATE)
                    AS joined_date,
                COALESCE(welfare_balances.welfare_balance, 0) AS welfare_balance,
                COALESCE(payouts.available_savings, 0) AS savings_balance
            FROM public.members members
            LEFT JOIN public.member_welfare_balances welfare_balances USING (member_id)
            LEFT JOIN public.sharing_member_payouts payouts USING (member_id)
            ORDER BY members.member_id;
            """
        )
        balances = cursor.fetchall()

        contribution_rows = []
        exempted_member_ids = []
        newly_exempted_member_ids = []
        assessed_request_funding = Decimal("0")
        outstanding_total = Decimal("0")
        if has_contribution_snapshot:
            cursor.execute(
                """
                SELECT
                    members.member_id,
                    members.full_name AS member_name,
                    COALESCE(members.joined_date, members.join_date, CURRENT_DATE)
                        AS joined_date,
                        contributions.target_amount,
                        contributions.is_exempt,
                        contributions.welfare_amount,
                        contributions.savings_amount,
                        COALESCE(paid.amount, 0) AS arrears_paid,
                    GREATEST(
                        contributions.outstanding_amount - COALESCE(paid.amount, 0),
                        0
                    ) AS outstanding_amount
                FROM public.welfare_request_member_contributions contributions
                JOIN public.members members USING (member_id)
                LEFT JOIN (
                    SELECT request_id, member_id, SUM(amount) AS amount
                    FROM public.welfare_request_member_arrears_payments
                    WHERE request_id = %s
                    GROUP BY request_id, member_id
                ) paid USING (request_id, member_id)
                WHERE contributions.request_id = %s
                ORDER BY members.member_id;
                """,
                (claim_id, claim_id),
            )
            contribution_rows = cursor.fetchall()
            for row in contribution_rows:
                if is_probationary_member(
                    row["joined_date"],
                    today=claim_created_on,
                ):
                    exempted_member_ids.append(row["member_id"])
                    if not row["is_exempt"]:
                        newly_exempted_member_ids.append(row["member_id"])
                        cursor.execute(
                            """
                            UPDATE public.welfare_request_member_contributions
                            SET target_amount = 0,
                                welfare_amount = 0,
                                savings_amount = 0,
                                outstanding_amount = 0,
                                is_exempt = TRUE
                            WHERE request_id = %s AND member_id = %s
                            RETURNING member_id;
                            """,
                            (claim_id, row["member_id"]),
                        )
                        if cursor.fetchone() is None:
                            raise RuntimeError(
                                "Could not exempt a probation-period welfare claim."
                            )
                    row["target_amount"] = Decimal("0")
                    row["is_exempt"] = True
                    row["welfare_amount"] = Decimal("0")
                    row["savings_amount"] = Decimal("0")
                    row["outstanding_amount"] = Decimal("0")

            outstanding_total = sum(
                (Decimal(str(row["outstanding_amount"])) for row in contribution_rows),
                Decimal("0"),
            )
            assessed_request_funding = sum(
                (
                    Decimal(str(row["welfare_amount"]))
                    + Decimal(str(row["savings_amount"]))
                    for row in contribution_rows
                    if not row["is_exempt"]
                ),
                Decimal("0"),
            )
        else:
            for member in balances:
                is_exempt = is_probationary_member(
                    member["joined_date"],
                    today=claim_created_on,
                )
                if is_exempt:
                    exempted_member_ids.append(member["member_id"])
                    newly_exempted_member_ids.append(member["member_id"])
                    from_welfare = Decimal("0")
                    from_savings = Decimal("0")
                    outstanding = Decimal("0")
                    member_target = Decimal("0")
                else:
                    from_welfare, from_savings, outstanding = (
                        _assess_member_welfare_contribution(
                            member["welfare_balance"],
                            member["savings_balance"],
                        )
                    )
                    member_target = WELFARE_CONTRIBUTION_PER_MEMBER
                contribution_rows.append(
                    {
                        "member_id": member["member_id"],
                        "member_name": member["full_name"],
                        "joined_date": member["joined_date"],
                        "target_amount": member_target,
                        "is_exempt": is_exempt,
                        "welfare_amount": from_welfare,
                        "savings_amount": from_savings,
                        "outstanding_amount": outstanding,
                    }
                )
                assessed_request_funding += from_welfare + from_savings
                outstanding_total += outstanding

        target_amount = sum(
            (row["target_amount"] for row in contribution_rows),
            Decimal("0"),
        )
        if has_contribution_snapshot:
            cursor.execute(
                """
                SELECT COALESCE(SUM(target_amount), 0) AS target_amount
                FROM public.welfare_request_member_contributions
                WHERE request_id = %s;
                """,
                (claim_id,),
            )
            target_row = cursor.fetchone()
            if target_row is None:
                raise RuntimeError("Welfare claim target query returned no result.")
            target_amount = Decimal(str(target_row["target_amount"]))
        target_amount = max(target_amount, previous_disbursed)
        if target_amount <= 0:
            if has_contribution_snapshot and newly_exempted_member_ids:
                cursor.execute(
                    """
                    INSERT INTO public.audit_logs (
                        entity_type, entity_id, action, actor_name, actor_role,
                        details, previous_value, new_value, created_at
                    )
                    VALUES (
                        'welfare_request', %s,
                        'probationary_members_exempted_from_welfare_claim',
                        %s, %s, %s, %s, %s, NOW()
                    );
                    """,
                    (
                        str(claim_id),
                        actor_name,
                        actor_role,
                        (
                            f"Exempted {len(newly_exempted_member_ids)} member(s) "
                            "because they were on probation when the claim was submitted."
                        ),
                        claim["current_stage"],
                        claim["current_stage"],
                    ),
                )
                for member_id in newly_exempted_member_ids:
                    cursor.execute(
                        """
                        INSERT INTO public.notifications (
                            recipient_type, recipient_id, title, message, is_read,
                            category, module_name, priority, action_link,
                            delivery_status, created_at
                        )
                        VALUES (
                            'Member', %s, 'Exempt from welfare claim contribution',
                            %s, FALSE, 'Welfare', 'Welfare Support', 'Normal',
                            '/api/welfare/view', 'Delivered', NOW()
                        );
                        """,
                        (
                            member_id,
                            (
                                f"You were on probation when welfare case "
                                f"{claim['case_number']} was submitted, so you are "
                                "exempt from this claim. No balance was deducted and "
                                "no arrears are owed for it."
                            ),
                        ),
                    )
            return {"error": "no_eligible_contributors"}
        remaining_target = max(target_amount - previous_disbursed, Decimal("0"))
        cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS arrears_paid
            FROM public.welfare_request_member_arrears_payments
            WHERE request_id = %s;
            """,
            (claim_id,),
        )
        arrears_paid_row = cursor.fetchone()
        if arrears_paid_row is None:
            raise RuntimeError("Welfare arrears payment query returned no result.")
        arrears_paid_for_request = Decimal(str(arrears_paid_row["arrears_paid"]))
        request_funding_remaining = max(
            assessed_request_funding + arrears_paid_for_request - previous_disbursed,
            Decimal("0"),
        )
        amount_disbursed = min(
            remaining_target,
            request_funding_remaining,
        )
        exemption_note = (
            f" {len(exempted_member_ids)} member(s) exempted because they were on "
            "probation when the claim was submitted."
            if exempted_member_ids
            else ""
        )
        if not has_contribution_snapshot:
            cursor.executemany(
                """
                INSERT INTO public.welfare_request_member_contributions (
                    request_id, member_id, target_amount, welfare_amount,
                    savings_amount, outstanding_amount, is_exempt
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                [
                    (
                        claim_id,
                        row["member_id"],
                        row["target_amount"],
                        row["welfare_amount"],
                        row["savings_amount"],
                        row["outstanding_amount"],
                        row["is_exempt"],
                    )
                    for row in contribution_rows
                ],
            )

        disbursement = None
        if amount_disbursed > 0:
            cursor.execute(
                """
                INSERT INTO public.welfare_request_disbursements (
                    request_id, target_amount, amount, disbursed_by, disbursed_role,
                    payment_reference, disbursed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp()::timestamp)
                RETURNING id, amount, target_amount, payment_reference, disbursed_at;
                """,
                (
                    claim_id,
                    target_amount,
                    amount_disbursed,
                    actor_name,
                    actor_role,
                    payment_reference,
                ),
            )
            disbursement = cursor.fetchone()

        cursor.execute(
            """
            UPDATE public.welfare_requests
            SET status = CASE
                    WHEN %s >= %s THEN 'Paid'
                    WHEN %s > 0 THEN 'Partially Paid'
                    ELSE 'Approved'
                END,
                current_stage = CASE
                    WHEN %s >= %s THEN 'Disbursed'
                    WHEN %s > 0 THEN 'Partially Disbursed'
                    ELSE 'Funding Shortfall'
                END,
                updated_at = NOW()
            WHERE id = %s
              AND current_stage IN (
                  'Executive Approved', 'Partially Disbursed', 'Funding Shortfall'
              )
            RETURNING id;
            """,
            (
                previous_disbursed + amount_disbursed,
                target_amount,
                previous_disbursed + amount_disbursed,
                previous_disbursed + amount_disbursed,
                target_amount,
                previous_disbursed + amount_disbursed,
                claim_id,
            ),
        )
        if not cursor.fetchone():
            return {"error": "claim_not_approved"}

        cursor.execute(
            """
            INSERT INTO public.audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'welfare_request', %s, %s,
                %s, %s, %s, %s, %s, NOW()
            );
            """,
            (
                str(claim_id),
                (
                    "welfare_support_disbursed"
                    if amount_disbursed > 0
                    else "welfare_funding_assessed"
                ),
                actor_name,
                actor_role,
                (
                    (
                        f"Disbursed UGX {amount_disbursed:,.2f}; cumulative "
                        f"disbursement UGX {previous_disbursed + amount_disbursed:,.2f} "
                        f"of UGX {target_amount:,.2f} target."
                        if amount_disbursed > 0
                        else "No cash was available to disburse; member deductions and "
                        "arrears were assessed and recorded."
                    )
                    + f" Member arrears UGX {outstanding_total:,.2f}."
                    + exemption_note
                ),
                claim["current_stage"],
                (
                    "Disbursed"
                    if previous_disbursed + amount_disbursed >= target_amount
                    else "Partially Disbursed"
                    if amount_disbursed > 0
                    else "Funding Shortfall"
                ),
            ),
        )

        disbursement_message = (
            f"was disbursed an additional UGX {amount_disbursed:,.2f}; cumulative "
            f"disbursement UGX {previous_disbursed + amount_disbursed:,.2f} of "
            f"UGX {target_amount:,.2f}. "
            if amount_disbursed > 0
            else "has been assessed, but no cash was available to disburse yet. "
        )
        global_message = (
            f"Welfare case {claim['case_number']} ({claim['support_category']}) "
            f"{disbursement_message}"
            f"UGX {outstanding_total:,.2f} remains outstanding across member "
            "contributions; check the Treasurer's welfare report for the member-by-member breakdown."
            f"{exemption_note}"
        )
        cursor.execute(
            """
            INSERT INTO public.notifications (
                recipient_type, recipient_id, title, message, is_read,
                category, module_name, priority, action_link, delivery_status, created_at
            )
            VALUES ('ALL', 'ALL', %s, %s, FALSE, 'Welfare', 'Welfare Support',
                    'High', '/api/welfare/view', 'Delivered', NOW());
            """,
            (f"Welfare support disbursed: {claim['case_number']}", global_message),
        )

        for member_id in newly_exempted_member_ids:
            cursor.execute(
                """
                INSERT INTO public.notifications (
                    recipient_type, recipient_id, title, message, is_read,
                    category, module_name, priority, action_link, delivery_status, created_at
                )
                VALUES (
                    'Member', %s, 'Exempt from welfare claim contribution',
                    %s, FALSE, 'Welfare', 'Welfare Support', 'Normal',
                    '/api/welfare/view', 'Delivered', NOW()
                );
                """,
                (
                    member_id,
                    (
                        f"You were on probation when welfare case "
                        f"{claim['case_number']} was submitted, so you are exempt "
                        "from this claim. No balance was deducted and no arrears "
                        "are owed for it."
                    ),
                ),
            )

        for row in contribution_rows if not has_contribution_snapshot else []:
            if row["is_exempt"]:
                continue
            personal_message = (
                f"Your UGX {row['welfare_amount']:,.2f} welfare balance and "
                f"UGX {row['savings_amount']:,.2f} savings were applied to welfare "
                f"case {claim['case_number']}."
            )
            if row["outstanding_amount"] > 0:
                personal_message += (
                    f" UGX {row['outstanding_amount']:,.2f} of your UGX "
                    f"{WELFARE_CONTRIBUTION_PER_MEMBER:,.2f} contribution remains due. "
                    "Please settle it promptly to avoid applicable penalties."
                )
            cursor.execute(
                """
                INSERT INTO public.notifications (
                    recipient_type, recipient_id, title, message, is_read,
                    category, module_name, priority, action_link, delivery_status, created_at
                )
                VALUES ('Member', %s, %s, %s, FALSE, 'Welfare',
                        'Welfare Support', %s, '/api/welfare/view', 'Delivered', NOW());
                """,
                (
                    row["member_id"],
                    f"Welfare contribution for {claim['case_number']}",
                    personal_message,
                    "High" if row["outstanding_amount"] > 0 else "Normal",
                ),
            )

        cursor.execute(
            """
            SELECT COALESCE(SUM(welfare_balance), 0) AS group_welfare_balance
            FROM public.member_welfare_balances;
            """
        )
        ending_welfare_balance = Decimal(
            str(cursor.fetchone()["group_welfare_balance"])
        )

        return {
            "claim": claim,
            "disbursement": disbursement,
            "contributions": contribution_rows,
            "target_amount": target_amount,
            "amount_disbursed": amount_disbursed,
            "cumulative_disbursed": previous_disbursed + amount_disbursed,
            "outstanding_total": outstanding_total,
            "ending_welfare_balance": ending_welfare_balance,
        }
