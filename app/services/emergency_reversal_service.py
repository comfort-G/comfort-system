from app.repositories import emergency_reversal_repo

ALLOWED_ACTION_TYPES = {"loan_approval", "welfare_disbursement"}


def fetch_latest_emergency_action() -> dict | None:
    return emergency_reversal_repo.get_latest_emergency_action()


def reverse_latest_action(
    action_type: str,
    action_id: int,
    actor_name: str,
    actor_role: str,
    reason: str,
    funds_received: bool,
) -> dict:
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ValueError("This financial action cannot be reversed here.")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise ValueError("Provide a clear reversal reason of at least 8 characters.")
    if len(normalized_reason) > 500:
        raise ValueError("The reversal reason cannot exceed 500 characters.")
    if not funds_received:
        raise ValueError(
            "Confirm that the funds have physically been received back before reversing."
        )

    result = emergency_reversal_repo.reverse_latest_emergency_action(
        action_type=action_type,
        action_id=action_id,
        actor_name=actor_name,
        actor_role=actor_role,
        reason=normalized_reason,
        funds_received=funds_received,
    )
    errors = {
        "no_reversible_action": "There is no recorded financial action to reverse.",
        "action_is_no_longer_latest": (
            "This is no longer the latest financial action. Refresh and review the current action."
        ),
        "funds_not_confirmed": (
            "Confirm that the funds have physically been received back before reversing."
        ),
        "reason_required": "A reason is required before reversing an action.",
        "member_funding_not_found": (
            "Individual member funding records are unavailable or do not cover "
            "this disbursement; no accounts were changed."
        ),
    }
    if result.get("error") == "action_not_reversible":
        raise ValueError(result["message"])
    if "error" in result:
        raise ValueError(errors[result["error"]])
    return result
