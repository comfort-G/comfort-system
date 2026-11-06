# app/services/admin_member_service.py
from datetime import date
from app.membership_rules import calculate_membership_tier
from app.repositories import admin_member_repo
from app.subscription_rules import (
    calculate_subscription_arrears,
    is_inactive_by_subscription_arrears,
)

def evaluate_member_statuses() -> list:
    """
    Business logic: Evaluates automatic classifications (Full, Partial, Probation, Active, Inactive)
    and applies any manual override set exclusively by the Chairperson.
    """
    members = admin_member_repo.get_all_members_with_financials()
    today = date.today()
    evaluated_list = []

    for m in members:
        joined = m["joined_date"]
        total_welfare = float(m["total_welfare"])
        auto_welfare_tier, days_in_group = calculate_membership_tier(
            joined, total_welfare, today
        )
        current_year_contributions = float(m["current_year_contributions"] or 0)
        subscription_debt, _ = calculate_subscription_arrears(
            current_year_contributions, today
        )
        manual_override = m.get("override_status")
        is_suspended = (m.get("account_status") or "").strip().casefold() == "suspended"

        # 2. Automatic Subscription Debt Rule Classification
        if is_inactive_by_subscription_arrears(subscription_debt):
            auto_debt_tier = "Inactive member"
        else:
            auto_debt_tier = "Active member"

        # Final Status: Chairperson override takes precedence if present, otherwise automatic system status
        final_status = (
            "Suspended"
            if is_suspended
            else manual_override or f"{auto_welfare_tier} / {auto_debt_tier}"
        )

        evaluated_list.append({
            "member_id": m["member_id"],
            "full_name": m["full_name"],
            "email": m["email"],
            "role": m["role"],
            "account_status": m["account_status"],
            "account_suspended": is_suspended,
            "suspension_reason": m.get("suspension_reason"),
            "suspended_at": m.get("suspended_at"),
            "joined_date": joined,
            "days_in_group": days_in_group,
            "total_welfare": total_welfare,
            "welfare_balance": float(m["welfare_balance"] or 0),
            "subscription_debt": subscription_debt,
            "auto_welfare_classification": auto_welfare_tier,
            "auto_debt_classification": auto_debt_tier,
            "manual_override": manual_override,
            "final_status": final_status
        })

    return evaluated_list

def chair_override_member_status(member_str_id: str, new_override_status: str | None) -> dict:
    """
    Business logic: Sets a manual status override. 
    Restricted entirely to the Chairperson.
    """
    result = admin_member_repo.set_member_status_override(member_str_id, new_override_status)
    if not result:
        raise ValueError("Member not found.")
        
    return {
        "status": "success",
        "message": f"Status override successfully updated for member {result['member_id']}.",
        "member_id": result["member_id"],
        "override_status": result["override_status"]
    }


def suspend_member_account(
    member_str_id: str,
    reason: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    if not reason.strip():
        raise ValueError("Provide a reason for suspending this member.")
    if member_str_id.strip().casefold() == actor_id.strip().casefold():
        raise ValueError("You cannot suspend your own account.")
    result = admin_member_repo.suspend_member_account(
        member_str_id, reason.strip(), actor_name, actor_role
    )
    if not result or result.get("error") == "member_not_found":
        raise ValueError("Member not found.")
    if result.get("error") == "already_suspended":
        raise ValueError("This member account is already suspended.")
    return {
        "status": "success",
        "message": f"Account for member {result['member_id']} has been suspended.",
        "member_id": result["member_id"],
        "account_status": result["status"],
    }


def restore_member_account(
    member_str_id: str,
    reason: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    if not reason.strip():
        raise ValueError("Provide a reason for restoring this member.")
    if member_str_id.strip().casefold() == actor_id.strip().casefold():
        raise ValueError("A suspended Chairperson must be restored by another Chairperson.")
    result = admin_member_repo.restore_member_account(
        member_str_id, reason.strip(), actor_name, actor_role
    )
    if not result or result.get("error") == "member_not_found":
        raise ValueError("Member not found.")
    if result.get("error") == "not_suspended":
        raise ValueError("This member account is not suspended.")
    return {
        "status": "success",
        "message": f"Account for member {result['member_id']} has been restored.",
        "member_id": result["member_id"],
        "account_status": result["status"],
    }