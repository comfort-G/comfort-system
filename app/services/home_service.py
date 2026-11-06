from datetime import date
from typing import Any

from app.membership_rules import calculate_membership_tier
from app.repositories import home_repository
from app.loan_interest import next_monthly_interest_due_date
from app.subscription_rules import (
    MONTHLY_SUBSCRIPTION_TARGET,
    calculate_subscription_arrears,
    is_inactive_by_subscription_arrears,
)


COMMITTEE_ROLES = {
    "chairperson",
    "vice chairperson",
    "secretary",
    "treasurer",
    "welfare",
}
ANNOUNCEMENT_MANAGER_ROLES = {"chairperson", "secretary"}


def _as_number(value: Any) -> float:
    return float(value or 0)


def _parse_announcement(record: dict[str, Any]) -> dict[str, Any]:
    message = record.get("message") or ""
    author_prefix, separator, content = message.partition("\n\n")
    if separator and author_prefix.startswith("Posted by: "):
        author = author_prefix.removeprefix("Posted by: ").strip()
        message = content
    else:
        author = "Comfort Group Committee"
    return {
        "id": record["id"],
        "title": record.get("title") or "Announcement",
        "content": message,
        "author": author or "Comfort Group Committee",
        "created_at": record.get("created_at"),
    }


def _calculate_next_loan_due_date(current_loan: dict[str, Any] | None) -> tuple[date | None, str]:
    if not current_loan:
        return None, "No reconciliation required"

    status = current_loan.get("status")
    if status not in {"Approved", "Active"}:
        return None, "No reconciliation required"

    loan_approved = current_loan.get("approved_date")
    last_interest_date = current_loan.get("last_interest_applied_date") or current_loan.get(
        "last_interest_applied_at"
    )

    if last_interest_date is None and loan_approved is not None:
        last_interest_date = loan_approved

    if last_interest_date is None:
        return None, "Interest date needs review"

    reference_date = last_interest_date
    if isinstance(reference_date, str):
        try:
            reference_date = date.fromisoformat(reference_date[:10])
        except ValueError:
            reference_date = None

    if reference_date is None:
        return None, "Interest date needs review"

    next_due_date = next_monthly_interest_due_date(reference_date)
    return next_due_date, "Interest date recorded"


def fetch_home_summary(member_id: str, role: str) -> dict[str, Any]:
    normalized_role = (role or "").strip().casefold()
    is_committee = normalized_role in COMMITTEE_ROLES
    records = home_repository.fetch_home_records(
        member_id,
        include_global_financials=is_committee,
    )
    if not records:
        raise ValueError("Member profile not found.")

    today = date.today()
    member = records["member"]
    member_financials = records["member_financials"]
    joined_date = member["joined_date"]
    total_savings = _as_number(member_financials["total_savings"])
    total_contributions = _as_number(member_financials["total_contributions"])
    current_year_contributions = _as_number(
        member_financials["current_year_contributions"]
    )
    total_welfare = _as_number(member_financials["total_welfare"])
    arrears, expected_contributions = calculate_subscription_arrears(
        current_year_contributions, today
    )
    activity_status = (
        "Inactive" if is_inactive_by_subscription_arrears(arrears) else "Active"
    )

    announcements = [_parse_announcement(row) for row in records["announcements"]]
    current_announcement = announcements[0] if announcements else None
    current_loan = records["current_loan"]
    loan_status = "No active loan"
    loan_due_date = None
    loan_reconciliation_status = "No reconciliation required"
    if current_loan:
        loan_status = current_loan["status"]
        if current_loan["status"] in {"Approved", "Active"}:
            loan_due_date, loan_reconciliation_status = _calculate_next_loan_due_date(current_loan)

    data: dict[str, Any] = {
        "profile": {
            "member_id": member["member_id"],
            "full_name": member["full_name"],
            "role": member["role"],
            "avatar_url": member.get("avatar_url"),
            "account_status": member["account_status"],
            "manual_override": member.get("override_status"),
            "joined_date": joined_date.isoformat()
            if isinstance(joined_date, date)
            else str(joined_date),
            "membership_tier": calculate_membership_tier(
                member["joined_date"], total_welfare, today
            )[0],
            "avatar_initials": "".join(
                part[0] for part in (member["full_name"] or "").split()[:2]
            ).upper(),
        },
        "subscription": {
            "total_contributions": total_contributions,
            "current_savings": total_savings,
            "welfare_paid": total_welfare,
            "welfare_balance": _as_number(member_financials["welfare_balance"]),
            "monthly_target": MONTHLY_SUBSCRIPTION_TARGET,
            "arrears": arrears,
            "expected_contributions": expected_contributions,
            "current_year_contributions": current_year_contributions,
            "pending_items": int(member_financials["pending_subscription_count"]),
            "activity_status": activity_status,
        },
        "loan": {
            "outstanding_balance": _as_number(
                member_financials["active_loan_balance"]
            ),
            "status": loan_status,
            "next_due_date": loan_due_date,
            "reconciliation_status": loan_reconciliation_status,
            "current_loan": (
                {
                    "reference": str(current_loan["loan_id"]),
                    "status": current_loan["status"],
                    "amount_requested": _as_number(
                        current_loan["amount_requested"]
                    ),
                    "outstanding_balance": _as_number(
                        current_loan["outstanding_balance"]
                    ),
                    "last_interest_applied_date": current_loan.get(
                        "last_interest_applied_date"
                    ) or current_loan.get("last_interest_applied_at"),
                }
                if current_loan
                else None
            ),
        },
        "sharing": {
            "overview": (
                "Year-end sharing updates are published by the committee "
                "when the annual distribution is confirmed."
            )
        },
        "announcements": {
            "current": current_announcement,
            "history": announcements[1:],
        },
        "membership": None,
        "permissions": {
            "is_committee": is_committee,
            "can_manage_announcements": normalized_role
            in ANNOUNCEMENT_MANAGER_ROLES,
        },
    }

    if is_committee:
        global_financials = records["global_financials"]
        data["global_financials"] = {
            key: _as_number(value)
            for key, value in global_financials.items()
            if key
            not in {
                "running_loan_count",
            }
        }
        data["global_financials"]["running_loan_count"] = int(
            global_financials["running_loan_count"]
        )
        data["global_financials"]["running_loans"] = [
            {
                "loan_id": loan["loan_id"],
                "member_id": loan["member_id"],
                "member_name": loan["full_name"],
                "status": loan["status"],
                "amount_requested": _as_number(loan["amount_requested"]),
                "outstanding_balance": _as_number(loan["outstanding_balance"]),
                "interest_accumulated": _as_number(loan["interest_accumulated"]),
                "approved_date": (
                    loan["approved_date"].isoformat()
                    if loan["approved_date"]
                    else None
                ),
                "last_interest_date": (
                    loan["last_interest_date"].isoformat()
                    if loan["last_interest_date"]
                    else None
                ),
                "next_due_date": (
                    _calculate_next_loan_due_date(
                        {
                            "status": loan["status"],
                            "approved_date": loan["approved_date"],
                            "last_interest_applied_date": loan["last_interest_date"],
                        }
                    )[0].isoformat()
                    if loan["last_interest_date"] or loan["approved_date"]
                    else None
                ),
            }
            for loan in records["global_running_loans"]
        ]

    member_rows = records["members"]
    membership_rows: list[dict[str, Any]] = []
    for row in member_rows:
        member_year_contributions = _as_number(row["current_year_contributions"])
        member_arrears, _ = calculate_subscription_arrears(
            member_year_contributions, today
        )
        is_suspended = (row["account_status"] or "").strip().casefold() == "suspended"
        is_active = (
            not is_suspended
            and not is_inactive_by_subscription_arrears(member_arrears)
        )
        required_action = (
            "No account action required."
            if is_active
            else "Review account status with the member."
        )
        if is_suspended:
            required_action = "Account suspended. Contact an executive for assistance."
        elif member_arrears > 0:
            required_action = (
                f"Follow up on UGX {member_arrears:,.0f} subscription arrears."
            )
        membership_rows.append(
            {
                "member_id": row["member_id"],
                "full_name": row["full_name"],
                "account_status": row["account_status"],
                "account_suspended": is_suspended,
                "is_active": is_active,
                "subscription_arrears": member_arrears,
                "required_action": required_action,
            }
        )

    active_members = [row for row in membership_rows if row["is_active"]]
    inactive_members = [row for row in membership_rows if not row["is_active"]]
    data["membership"] = {
        "total": len(membership_rows),
        "active": len(active_members),
        "inactive": len(inactive_members),
        "active_members": active_members,
        "inactive_members": inactive_members,
    }

    return data


def publish_announcement(title: str, content: str, author_name: str) -> dict[str, Any]:
    record = home_repository.publish_announcement(title, content, author_name)
    return _parse_announcement(record)
