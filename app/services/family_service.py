from app.repositories import family_repo


class FamilyRelativeNotFoundError(LookupError):
    """Raised when a relative does not exist for the authenticated member."""


_REPOSITORY_ERRORS = {
    "member_not_found": "Member record not found.",
    "relative_not_found": "Family record not found.",
    "registry_locked": "This registry was submitted and can only be changed by the Chairperson.",
    "already_submitted": "This family registry has already been submitted.",
    "empty_registry": "Add at least one relative before submitting your registry.",
    "deceased_status_final": "A relative marked Deceased cannot be changed back to Alive.",
    "status_change_requires_chairperson": "Only the Chairperson can change a relative's vital status.",
    "chairperson_required": "Only the Chairperson can edit this submitted registry.",
    "registry_not_submitted": "This registry has not been submitted for review.",
    "already_reviewed": "This registry has already been reviewed.",
}


def _validate_relative_fields(
    member_id: str,
    relationship_type: str,
    full_legal_name: str,
    primary_contact: str,
    vital_status: str,
) -> tuple[str, str, str, str, str]:
    values = {
        "Member ID": member_id,
        "Relationship type": relationship_type,
        "Full legal name": full_legal_name,
        "Primary contact": primary_contact,
        "Vital status": vital_status,
    }
    cleaned = {field: value.strip() for field, value in values.items()}
    for field, value in cleaned.items():
        if not value:
            raise ValueError(f"{field} is required.")

    valid_statuses = {"alive": "Alive", "deceased": "Deceased"}
    status = valid_statuses.get(cleaned["Vital status"].casefold())
    if status is None:
        raise ValueError("Vital status must be either Alive or Deceased.")

    return (
        cleaned["Member ID"],
        cleaned["Relationship type"],
        cleaned["Full legal name"],
        cleaned["Primary contact"],
        status,
    )


def _raise_repository_error(result: dict) -> None:
    error = result.get("error")
    if error == "relative_not_found":
        raise FamilyRelativeNotFoundError(_REPOSITORY_ERRORS[error])
    if error:
        raise ValueError(_REPOSITORY_ERRORS.get(error, "Could not update the family registry."))


def list_member_relatives(member_id: str) -> dict:
    member_id = member_id.strip()
    if not member_id:
        raise ValueError("Member ID is required.")
    return family_repo.get_registry_by_member(member_id)


def list_executive_registries() -> list[dict]:
    return family_repo.get_executive_registries()


def submit_member_registry(member_id: str, actor_name: str, actor_role: str) -> dict:
    result = family_repo.submit_registry(member_id, actor_name, actor_role)
    _raise_repository_error(result)
    return {"status": "success", **result}


def add_member_relative(
    member_id: str,
    relationship_type: str,
    full_legal_name: str,
    primary_contact: str,
    vital_status: str,
    actor_name: str,
    actor_role: str,
    chairperson_edit: bool = False,
) -> dict:
    values = _validate_relative_fields(
        member_id,
        relationship_type,
        full_legal_name,
        primary_contact,
        vital_status,
    )
    if not chairperson_edit and values[4] != "Alive":
        raise ValueError("Only the Chairperson can set a relative's status to Deceased.")
    result = family_repo.insert_relative(
        *values,
        actor_name=actor_name,
        actor_role=actor_role,
        chairperson_edit=chairperson_edit,
    )
    _raise_repository_error(result)
    return {"status": "success", "relative": result["relative"]}


def update_member_relative(
    relative_id: int,
    relationship_type: str,
    full_legal_name: str,
    primary_contact: str,
    vital_status: str,
    actor_name: str,
    actor_role: str,
    expected_member_id: str | None = None,
    chairperson_edit: bool = False,
) -> dict:
    if relative_id < 1:
        raise ValueError("Relative ID must be positive.")
    values = _validate_relative_fields(
        expected_member_id or "chairperson",
        relationship_type,
        full_legal_name,
        primary_contact,
        vital_status,
    )
    result = family_repo.update_relative(
        relative_id,
        *values[1:],
        actor_name=actor_name,
        actor_role=actor_role,
        chairperson_edit=chairperson_edit,
        expected_member_id=expected_member_id,
    )
    _raise_repository_error(result)
    return {"status": "success", "relative": result["relative"]}


def delete_member_relative(
    relative_id: int,
    member_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    if relative_id < 1:
        raise ValueError("Relative ID must be positive.")
    member_id = member_id.strip()
    if not member_id:
        raise ValueError("Member ID is required.")
    result = family_repo.delete_relative(relative_id, member_id, actor_name, actor_role)
    _raise_repository_error(result)
    return {"status": "success", "message": "Family record deleted."}


def review_member_registry(member_id: str, actor_name: str, actor_role: str) -> dict:
    result = family_repo.mark_registry_reviewed(member_id, actor_name, actor_role)
    _raise_repository_error(result)
    return {"status": "success", **result}
