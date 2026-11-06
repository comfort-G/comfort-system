from datetime import date

from app.membership_rules import calculate_membership_tier
from app.repositories import dashboard_repo
from app.subscription_rules import (
    calculate_subscription_arrears,
    is_inactive_by_subscription_arrears,
)


def fetch_member_dashboard_summary(member_str_id: str) -> dict:
    member = dashboard_repo.get_member_dashboard_data(member_str_id)
    if not member:
        raise ValueError("Member profile not found.")

    welfare_tier, _ = calculate_membership_tier(
        member["joined_date"], float(member["total_welfare"]), date.today()
    )
    total_welfare = float(member["total_welfare"])
    current_year_contributions = float(member["current_year_contributions"] or 0)
    subscription_debt, _ = calculate_subscription_arrears(
        current_year_contributions, date.today()
    )

    debt_tier = (
        "Inactive member"
        if is_inactive_by_subscription_arrears(subscription_debt)
        else "Active member"
    )
    manual_override = member.get("override_status")

    return {
        "member_id": member["member_id"],
        "full_name": member["full_name"],
        "role": member["role"],
        "account_status": member["account_status"],
        "total_savings": float(member["total_savings"]),
        "welfare_balance": float(member["welfare_balance"]),
        "active_loan_balance": float(member["active_loan_balance"]),
        "welfare_tier": welfare_tier,
        "debt_tier": debt_tier,
        "final_status": manual_override or f"{welfare_tier} / {debt_tier}",
        "manual_override": manual_override,
    }
