# app/services/loan_service.py
from app.repositories import loan_repo
import math
import re
from app.subscription_rules import INACTIVE_ARREARS_THRESHOLD

def fetch_member_loans(member_str_id: str) -> dict:
    loans = loan_repo.get_loans_by_member(member_str_id)
    active_loan = next(
        (
            loan
            for loan in loans
            if (loan.get("status") or "").strip().casefold()
            in {"pending", "approved", "active"}
        ),
        None,
    )
    
    return {
        "member_id": member_str_id,
        "latest_loan_snapshot": active_loan,
        "loan_history": loans
    }

def apply_for_loan(
    member_str_id: str,
    amount: float,
    purpose: str,
    mobile_money_number: str,
) -> dict:
    """
    Enforces all loan eligibility rules:
    1. Member must exist and be active.
    2. Maximum loan limit is UGX 300,000.
    3. Member cannot have a running/pending/active loan.
    """
    # 2. Check maximum loan amount limit (UGX 300,000)
    MAX_LOAN_LIMIT = 300000.0
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Loan request amount must be greater than zero.")
    if amount > MAX_LOAN_LIMIT:
        raise ValueError(f"Loan request exceeds maximum allowed limit of UGX {MAX_LOAN_LIMIT:,.0f}.")

    normalized_number = re.sub(r"[\s()-]", "", mobile_money_number or "")
    if not re.fullmatch(r"\+?\d{9,15}", normalized_number):
        raise ValueError(
            "Enter a valid Mobile Money number with 9 to 15 digits, "
            "including the country code if applicable."
        )

    result = loan_repo.submit_loan_application_if_eligible(
        member_str_id,
        amount,
        purpose,
        normalized_number,
    )
    if result is None:
        raise RuntimeError("Loan application eligibility check returned no result.")
    if result.get("error") == "member_not_found":
        raise ValueError("Member profile not found.")
    if result.get("error") == "member_account_inactive":
        raise ValueError(
            "Loan eligibility denied: your account is "
            f"{result['account_status']}. Contact an executive to confirm or update "
            "your account status before applying."
        )
    if result.get("error") == "member_on_probation":
        raise ValueError(
            "Loan eligibility denied: members must complete the 60-day probation "
            "period before applying."
        )
    if result.get("error") == "member_classified_inactive":
        if result.get("override_status"):
            raise ValueError(
                "Loan eligibility denied: your current member-status override is "
                f"'{result['override_status']}'. Ask the Chairperson to review it "
                "if it is incorrect."
            )
        raise ValueError(
            "Loan eligibility denied: your current subscription arrears are "
            f"UGX {result['arrears']:,.0f}, above the UGX "
            f"{INACTIVE_ARREARS_THRESHOLD:,.0f} inactivity threshold. "
            "Please settle the arrears or ask the Treasurer to verify your ledger."
        )
    if result.get("error") == "existing_loan":
        raise ValueError(
            f"Loan eligibility denied: loan #{result['loan_id']} is currently "
            f"{result['loan_status']}. You can apply again after that loan is cleared."
        )
    
    return {
        "status": "success",
        "message": (
            "Loan application submitted successfully and is pending executive review. "
            "It is not approved or disbursed until an executive completes the review."
        ),
        "loan_id": result["id"]
    }

def fetch_pending_loans_for_review() -> list:
    return loan_repo.get_pending_loans()

def review_loan_application(
    loan_id: int,
    decision: str,
    executive_name: str,
    rejection_reason: str = "",
) -> dict:
    normalized_decision = decision.capitalize()
    if normalized_decision not in ["Approved", "Rejected"]:
        raise ValueError("Invalid decision. Must be 'Approved' or 'Rejected'.")
    if normalized_decision == "Rejected" and not rejection_reason.strip():
        raise ValueError(
            "Enter the specific eligibility requirement or reason for rejecting this application."
        )
        
    if normalized_decision == "Approved":
        result = loan_repo.approve_loan_in_db(loan_id, executive_name)
    else:
        result = loan_repo.reject_loan_in_db(
            loan_id,
            executive_name,
            rejection_reason.strip(),
        )
        
    if result is None:
        raise ValueError("Loan application not found or no longer pending.")
        
    return {
        "status": "success",
        "message": f"Loan application has been successfully {normalized_decision.lower()}.",
        "loan_id": result["id"],
        "new_status": result["status"]
    }