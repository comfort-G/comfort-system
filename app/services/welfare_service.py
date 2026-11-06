# app/services/welfare_service.py
from decimal import Decimal

from app.repositories import welfare_repo
from app.repositories import family_repo
from app.membership_rules import calculate_membership_tier
from app.welfare_rules import (
    MINIMUM_WELFARE_BALANCE,
    is_eligible_beneficiary,
    normalize_welfare_category,
)


def get_member_welfare_eligibility(member_id: str) -> dict:
    member = welfare_repo.get_member_welfare_eligibility(member_id)
    if member is None:
        raise ValueError("Member profile not found.")

    membership_tier, _ = calculate_membership_tier(
        member["joined_date"],
        0,
    )
    welfare_balance = Decimal(str(member["welfare_balance"] or 0))
    reasons = []
    if membership_tier == "Probation member":
        reasons.append("Probation members cannot apply for welfare support.")
    if welfare_balance < MINIMUM_WELFARE_BALANCE:
        reasons.append(
            "A welfare balance of at least UGX 40,000 is required to apply."
        )

    return {
        "eligible": not reasons,
        "membership_tier": membership_tier,
        "welfare_balance": float(welfare_balance),
        "minimum_welfare_balance": MINIMUM_WELFARE_BALANCE,
        "reasons": reasons,
    }


def get_eligible_beneficiaries(
    member_id: str,
    member_name: str,
    support_category: str,
) -> dict:
    category = normalize_welfare_category(support_category)
    if category is None:
        raise ValueError(
            "Choose Wedding, Traditional Introduction, Illness, or Death."
        )

    eligibility = get_member_welfare_eligibility(member_id)
    if not eligibility["eligible"]:
        return {
            **eligibility,
            "beneficiaries": [],
        }

    beneficiaries = [
        {
            "id": "self",
            "full_legal_name": member_name,
            "relationship_type": "Member",
            "vital_status": "Alive",
            "is_self": True,
        }
    ]
    if category in {"Illness", "Death"}:
        relatives = family_repo.get_relatives_by_member(member_id)
        beneficiaries.extend(
            {
                "id": relative["id"],
                "full_legal_name": relative["full_legal_name"],
                "relationship_type": relative["relationship_type"],
                "vital_status": relative["vital_status"],
                "is_self": False,
            }
            for relative in relatives
            if is_eligible_beneficiary(category, relative)
        )
    return {
        **eligibility,
        "beneficiaries": beneficiaries,
    }


def fetch_member_welfare_dashboard(member_str_id: str) -> dict:
    """Business logic: Gathers member welfare claims history."""
    claims = welfare_repo.get_welfare_claims_by_member(member_str_id)
    return {"member_id": member_str_id, "claims_history": claims}

def submit_welfare_claim(
    member_id: str,
    member_name: str,
    support_category: str,
    beneficiary_id: str,
    description: str,
    evidence_file_url: str,
) -> dict:
    """Business logic: Validates and saves a new welfare request."""
    category = normalize_welfare_category(support_category)
    if category is None:
        raise ValueError(
            "Choose Wedding, Traditional Introduction, Illness, or Death."
        )
    eligibility = get_member_welfare_eligibility(member_id)
    if not eligibility["eligible"]:
        raise ValueError(" ".join(eligibility["reasons"]))
    if not beneficiary_id.strip():
        raise ValueError("Select the person this welfare claim is for.")
    if not description.strip():
        raise ValueError("Claim description is required.")

    result = welfare_repo.insert_welfare_claim(
        member_id=member_id,
        member_name=member_name,
        support_category=category,
        beneficiary_id=beneficiary_id,
        description=description,
        evidence_file_url=evidence_file_url
    )
    if not isinstance(result, dict):
        raise RuntimeError("Welfare claim insert returned no result.")
    errors = {
        "invalid_support_category": (
            "Choose Wedding, Traditional Introduction, Illness, or Death."
        ),
        "beneficiary_not_found": (
            "That person is not in your Family Registry. Add them there before "
            "submitting this claim."
        ),
        "beneficiary_relationship_ineligible": (
            f"{category} support does not cover that registered relationship."
        ),
        "beneficiary_vital_status_ineligible": (
            "Illness claims require the registered relative to be marked Alive; "
            "Death claims also require them to be marked Alive. Update the Family "
            "Registry if its status is incorrect."
        ),
    }
    if result.get("error"):
        raise ValueError(errors[result["error"]])
    return {
        "status": "success",
        "message": (
            f"Welfare claim {result['case_number']} for "
            f"{result['beneficiary_relationship']} "
            f"{result['beneficiary_name']} submitted successfully."
        ),
        "claim_id": result["id"],
        "case_number": result["case_number"],
    }


def fetch_staff_welfare_queue() -> list:
    """Business logic: Retrieves all welfare cases for staff moderation."""
    return welfare_repo.get_all_welfare_claims_for_staff()

def moderate_welfare_claim(
    claim_id: int,
    new_status: str,
    new_stage: str,
    role: str,
    comment: str,
    actor_name: str,
) -> dict:
    """Enforces the role-specific welfare review sequence."""
    result = welfare_repo.update_welfare_claim_stage(
        claim_id=claim_id,
        new_status=new_status,
        new_stage=new_stage,
        role=role,
        actor_name=actor_name,
        comment_text=comment
    )
    errors = {
        "role_not_allowed": "Only Welfare staff, the Treasurer, or the Chairperson may review welfare claims.",
        "transition_not_allowed": "Your role cannot perform that welfare status transition.",
        "claim_not_found": "Welfare claim not found.",
        "invalid_current_stage": "The claim is not at the required stage for this action.",
    }
    if "error" in result:
        raise ValueError(errors[result["error"]])

    if not result:
        raise ValueError("Welfare claim not found.")

    return {
        "status": "success",
        "message": f"Claim {result['case_number']} updated successfully to stage '{new_stage}'.",
        "claim_id": result["id"],
        "current_stage": result["current_stage"]
    }


def disburse_welfare_claim(claim_id: int, actor_name: str, actor_role: str) -> dict:
    result = welfare_repo.disburse_welfare_claim(
        claim_id=claim_id,
        actor_name=actor_name,
        actor_role=actor_role,
    )
    errors = {
        "claim_not_found": "Welfare claim not found.",
        "claim_not_approved": "Only a Chairperson-approved welfare claim can be disbursed.",
        "no_registered_members": "Cannot disburse welfare support because no members are registered.",
        "no_eligible_contributors": "Cannot disburse this claim because no members were eligible to contribute when it was submitted.",
        "legacy_disbursement_exists": "A legacy welfare payment is already recorded for this claim; it cannot be paid again.",
    }
    if "error" in result:
        raise ValueError(errors[result["error"]])

    amount = result["amount_disbursed"]
    outstanding = result["outstanding_total"]
    if amount == 0:
        message = (
            f"Funding assessment recorded for case {result['claim']['case_number']}; "
            f"no funds were available to disburse. Outstanding member contributions: "
            f"UGX {outstanding:,.2f}."
        )
    else:
        message = (
            f"Disbursed UGX {amount:,.2f} for case "
            f"{result['claim']['case_number']}. Cumulative disbursement: "
            f"UGX {result['cumulative_disbursed']:,.2f} of "
            f"UGX {result['target_amount']:,.2f}. Outstanding member contributions: "
            f"UGX {outstanding:,.2f}."
        )
    return {
        "status": "success",
        "message": message,
        "claim_id": claim_id,
        "amount_disbursed": float(amount),
        "target_amount": float(result["target_amount"]),
        "outstanding_total": float(outstanding),
        "ending_welfare_balance": float(result["ending_welfare_balance"]),
        "payment_reference": (
            result["disbursement"]["payment_reference"]
            if result["disbursement"]
            else None
        ),
    }