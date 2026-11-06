# app/services/finance_service.py
from app.repositories import finance_repo

def calculate_subscription_summary(member_id: str) -> dict:
    """
    Business logic: Fetches subscription history and calculates 
    total paid and outstanding ledger metrics.
    """
    records = finance_repo.fetch_member_subscriptions(member_id)
    
    total_paid = sum(
        float(item["amount"] or 0)
        for item in records
        if (item.get("status") or "").strip().casefold() == "paid"
    )
    pending_count = sum(
        1
        for item in records
        if (item.get("status") or "").strip().casefold() == "pending"
    )
    
    return {
        "member_id": member_id,
        "total_paid": total_paid,
        "pending_verifications": pending_count,
        "history": records
    }