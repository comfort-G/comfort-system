# app/repositories/finance_repo.py
from app.database import get_db

def fetch_member_subscriptions(member_id: str):
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                member_id,
                COALESCE(amount_paid, 0) AS amount,
                billing_month AS payment_date,
                status
            FROM subscriptions 
            WHERE member_id = %s 
            ORDER BY payment_date DESC;
            """,
            (member_id,)
        )
        return cursor.fetchall()