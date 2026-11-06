# app/repositories/subscription_repo.py
# app/repositories/subscription_repo.py
from datetime import date
from decimal import Decimal
from typing import Any

from app.database import get_db
from app.subscription_allocation import allocate_subscription_payment, month_start

def get_subscriptions_by_member_str(member_str_id: str):
    """Fetches a member's monthly subscription history and paid totals."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                        THEN COALESCE(amount_paid, 0)
                        ELSE 0
                    END
                ), 0.0) AS total_paid_contributions,
                COALESCE(SUM(
                    CASE
                        WHEN LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                          AND billing_month >= DATE_TRUNC('year', CURRENT_DATE)::date
                          AND billing_month < (
                              DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
                          )::date
                        THEN COALESCE(amount_paid, 0)
                        ELSE 0
                    END
                ), 0.0) AS current_year_paid_contributions,
                COALESCE((
                    SELECT payouts.remaining_savings
                    FROM public.sharing_member_payouts payouts
                    WHERE payouts.member_id = %s
                ), 0) AS current_savings
            FROM subscriptions
            WHERE member_id = %s;
            """,
            (member_str_id, member_str_id),
        )
        summary = cursor.fetchone()

        cursor.execute(
            """
            SELECT id, member_id, billing_month AS payment_date, amount_paid AS amount, status, updated_at AS created_at
            FROM subscriptions
            WHERE member_id = %s
            ORDER BY billing_month DESC;
            """,
            (member_str_id,)
        )
        return {
            "history": cursor.fetchall(),
            "total_paid_contributions": summary["total_paid_contributions"],
            "current_year_paid_contributions": summary[
                "current_year_paid_contributions"
            ],
            "current_savings": summary["current_savings"],
        }

def insert_payment_proof(
    member_id: str,
    member_name: str,
    amount: float,
    proof_url: str,
    notes: str,
    payment_method: str,
    transaction_reference: str | None,
    cloudinary_public_id: str,
    payment_month: int | None,
    payment_year: int | None,
):
    """Inserts a new subscription payment proof upload into Neon."""
    payment_date = date.today()
    month = payment_month or payment_date.month
    year = payment_year or payment_date.year
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO subscription_payment_proofs (
                member_id, member_name, subscription_month, subscription_year,
                amount_paid, payment_method, transaction_reference, comment,
                cloudinary_file_url, cloudinary_public_id, verification_status,
                upload_timestamp
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending Verification', NOW())
            RETURNING proof_id, verification_status;
            """,
            (
                member_id, member_name, month, year, amount, payment_method,
                transaction_reference, notes, proof_url, cloudinary_public_id,
            ),
        )
        return cursor.fetchone()


def _member_allocation_state(
    cursor: Any,
    member_id: str,
    lock_member: bool,
) -> tuple[date, dict[date, Decimal]] | None:
    lock_clause = " FOR UPDATE" if lock_member else ""
    cursor.execute(
        f"""
        SELECT COALESCE(joined_date, join_date, CURRENT_DATE) AS joined_date
        FROM public.members
        WHERE member_id = %s
        {lock_clause};
        """,
        (member_id,),
    )
    member = cursor.fetchone()
    if not member:
        return None

    cursor.execute(
        """
        SELECT
            DATE_TRUNC('month', billing_month)::date AS billing_month,
            COALESCE(SUM(amount_paid), 0) AS amount_paid
        FROM public.subscriptions
        WHERE member_id = %s
          AND LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
        GROUP BY DATE_TRUNC('month', billing_month)::date;
        """,
        (member_id,),
    )
    paid_by_month = {}
    for row in cursor.fetchall():
        paid = Decimal(str(row["amount_paid"] or 0))
        if not paid.is_finite() or paid < 0:
            raise ValueError(
                "The existing subscription ledger contains an invalid monthly total. "
                "Correct it before allocating another payment."
            )
        paid_by_month[row["billing_month"]] = paid
    current_year_start = date(date.today().year, 1, 1)
    start_month = max(month_start(member["joined_date"]), current_year_start)
    return start_month, paid_by_month


def plan_subscription_allocation(
    cursor: Any,
    member_id: str,
    amount: Decimal,
    lock_member: bool,
) -> list[dict[str, Decimal | date]] | None:
    state = _member_allocation_state(cursor, member_id, lock_member)
    if not state:
        return None
    start_month, paid_by_month = state
    return allocate_subscription_payment(amount, paid_by_month, start_month)


def serialize_subscription_allocations(
    allocations: list[dict[str, Decimal | date]],
) -> list[dict[str, str]]:
    return [
        {
            "billing_month": allocation["billing_month"].isoformat(),
            "amount": str(allocation["amount"]),
        }
        for allocation in allocations
    ]


def expected_subscription_allocations_match(
    expected: list[dict[str, Any]] | None,
    actual: list[dict[str, Decimal | date]],
) -> bool:
    if expected is None:
        return True
    try:
        normalized_expected = [
            (
                month_start(
                    item["billing_month"]
                    if isinstance(item["billing_month"], date)
                    else date.fromisoformat(str(item["billing_month"]))
                ),
                Decimal(str(item["amount"])),
            )
            for item in expected
        ]
    except (KeyError, TypeError, ValueError):
        return False
    normalized_actual = [
        (item["billing_month"], item["amount"]) for item in actual
    ]
    return normalized_expected == normalized_actual


def preview_member_subscription_allocation(
    member_id: str,
    amount: Decimal,
) -> dict[str, Any] | None:
    with get_db() as cursor:
        state = _member_allocation_state(cursor, member_id, lock_member=False)
        if not state:
            return None
        start_month, paid_by_month = state
        allocations = allocate_subscription_payment(
            amount, paid_by_month, start_month
        )
        return {"allocations": serialize_subscription_allocations(allocations)}


def preview_subscription_proof_allocation(
    proof_id: int,
    amount: Decimal,
) -> dict[str, Any] | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT member_id, verification_status
            FROM public.subscription_payment_proofs
            WHERE proof_id = %s;
            """,
            (proof_id,),
        )
        proof = cursor.fetchone()
        if not proof:
            return None
        if (proof["verification_status"] or "").strip().casefold() != "pending verification":
            return {"error": "already_reviewed"}
        state = _member_allocation_state(
            cursor, proof["member_id"], lock_member=False
        )
        if not state:
            return {"error": "member_not_found"}
        start_month, paid_by_month = state
        allocations = allocate_subscription_payment(
            amount, paid_by_month, start_month
        )
        return {
            "member_id": proof["member_id"],
            "allocations": serialize_subscription_allocations(allocations),
        }


def _apply_subscription_allocations(
    cursor: Any,
    member_id: str,
    allocations: list[dict[str, Decimal | date]],
) -> list[int]:
    subscription_ids: list[int] = []
    for allocation in allocations:
        billing_month = allocation["billing_month"]
        amount = allocation["amount"]
        cursor.execute(
            """
            SELECT id
            FROM public.subscriptions
            WHERE member_id = %s
              AND DATE_TRUNC('month', billing_month)::date = %s
              AND LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
            ORDER BY id
            FOR UPDATE;
            """,
            (member_id, billing_month),
        )
        existing = cursor.fetchall()
        if existing:
            subscription_id = existing[0]["id"]
            cursor.execute(
                """
                UPDATE public.subscriptions
                SET amount_paid = COALESCE(amount_paid, 0) + %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id;
                """,
                (amount, subscription_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO public.subscriptions (
                    member_id, billing_month, amount_paid, status, updated_at
                )
                VALUES (%s, %s, %s, 'Paid', NOW())
                RETURNING id;
                """,
                (member_id, billing_month, amount),
            )
            subscription_id = cursor.fetchone()["id"]
        subscription_ids.append(subscription_id)
    return subscription_ids


def apply_subscription_allocations(
    cursor: Any,
    member_id: str,
    allocations: list[dict[str, Decimal | date]],
) -> list[int]:
    return _apply_subscription_allocations(cursor, member_id, allocations)


def get_pending_subscription_proofs() -> list[dict[str, Any]]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                proof_id, member_id, member_name, subscription_month,
                subscription_year,
                CASE
                    WHEN LOWER(BTRIM(COALESCE(verification_status, '')))
                        = 'pending verification' THEN NULL
                    ELSE amount_paid
                END AS amount_paid,
                payment_method,
                transaction_reference, comment, cloudinary_file_url,
                upload_timestamp, verification_status
            FROM subscription_payment_proofs
            WHERE LOWER(BTRIM(COALESCE(verification_status, ''))) = 'pending verification'
            ORDER BY upload_timestamp, proof_id;
            """
        )
        return cursor.fetchall()


def review_subscription_payment_proof(
    proof_id: int,
    decision: str,
    actor_name: str,
    actor_role: str,
    comment: str,
    amount: Decimal | None = None,
    expected_allocations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                proof_id, member_id, member_name, subscription_month,
                subscription_year, amount_paid, verification_status
            FROM subscription_payment_proofs
            WHERE proof_id = %s
            FOR UPDATE;
            """,
            (proof_id,),
        )
        proof = cursor.fetchone()
        if not proof:
            return None

        if (proof["verification_status"] or "").strip().casefold() != "pending verification":
            return {"error": "already_reviewed"}

        allocations: list[dict[str, Decimal | date]] = []
        subscription_ids: list[int] = []
        if decision == "Paid":
            cursor.execute(
                "SELECT member_id FROM members WHERE member_id = %s FOR UPDATE;",
                (proof["member_id"],),
            )
            if not cursor.fetchone():
                return {"error": "member_not_found"}
            if amount is None or amount <= 0:
                return {"error": "invalid_amount"}
            if not expected_allocations:
                return {"error": "preview_required"}
            state = _member_allocation_state(
                cursor, proof["member_id"], lock_member=False
            )
            if not state:
                return {"error": "member_not_found"}
            start_month, paid_by_month = state
            allocations = allocate_subscription_payment(
                amount, paid_by_month, start_month
            )
            if not expected_subscription_allocations_match(
                expected_allocations, allocations
            ):
                return {
                    "error": "allocation_changed",
                    "allocations": serialize_subscription_allocations(allocations),
                }
            subscription_ids = _apply_subscription_allocations(
                cursor, proof["member_id"], allocations
            )
            cursor.execute(
                """
                UPDATE public.subscription_payment_proofs
                SET amount_paid = %s
                WHERE proof_id = %s;
                """,
                (amount, proof_id),
            )

        cursor.execute(
            """
            UPDATE subscription_payment_proofs
            SET verification_status = %s,
                verified_by = %s,
                verification_date = NOW(),
                verification_comment = %s
            WHERE proof_id = %s
              AND LOWER(BTRIM(COALESCE(verification_status, ''))) = 'pending verification'
            RETURNING proof_id, verification_status;
            """,
            (decision, actor_name, comment, proof_id),
        )
        updated_proof = cursor.fetchone()
        if not updated_proof:
            return {"error": "already_reviewed"}

        allocation_summary = ", ".join(
            f"{item['billing_month']:%B %Y}: UGX {item['amount']:,.2f}"
            for item in allocations
        )
        audit_details = comment or f"Subscription proof {decision.casefold()}."
        if allocation_summary:
            audit_details = f"{audit_details} Allocated {allocation_summary}."

        cursor.execute(
            """
            INSERT INTO audit_logs (
                entity_type, entity_id, action, actor_name, actor_role,
                details, previous_value, new_value, created_at
            )
            VALUES (
                'subscription_payment_proof', %s, %s, %s, %s, %s,
                'Pending Verification', %s, NOW()
            );
            """,
            (
                str(proof_id),
                f"subscription_proof_{decision.casefold()}",
                actor_name,
                actor_role,
                audit_details,
                decision,
            ),
        )
        return {
            "proof_id": proof_id,
            "status": decision,
            "subscription_ids": subscription_ids,
            "allocations": serialize_subscription_allocations(allocations),
            "amount_paid": str(amount) if amount is not None else None,
        }