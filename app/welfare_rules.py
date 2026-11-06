import re
from typing import Any


MINIMUM_WELFARE_BALANCE = 40_000

WELFARE_CATEGORIES = {
    "wedding": "Wedding",
    "traditional introduction": "Traditional Introduction",
    "illness": "Illness",
    "death": "Death",
}

ILLNESS_RELATIONSHIPS = {"spouse", "child"}
DEATH_RELATIONSHIPS = {"spouse", "child", "parent", "parent_in_law"}

_RELATIONSHIP_ALIASES = {
    "spouse": "spouse",
    "wife": "spouse",
    "husband": "spouse",
    "child": "child",
    "children": "child",
    "son": "child",
    "daughter": "child",
    "parent": "parent",
    "parents": "parent",
    "mother": "parent",
    "father": "parent",
    "parent in law": "parent_in_law",
    "parents in law": "parent_in_law",
    "father in law": "parent_in_law",
    "mother in law": "parent_in_law",
}


def normalize_welfare_category(value: str) -> str | None:
    return WELFARE_CATEGORIES.get(value.strip().casefold())


def normalize_family_relationship(value: str) -> str | None:
    normalized = re.sub(r"[\s_-]+", " ", value.strip().casefold())
    return _RELATIONSHIP_ALIASES.get(normalized)


def is_eligible_beneficiary(category: str, beneficiary: dict[str, Any]) -> bool:
    if beneficiary.get("is_self"):
        return True

    relationship = normalize_family_relationship(
        str(beneficiary.get("relationship_type") or "")
    )
    vital_status = str(beneficiary.get("vital_status") or "").strip().casefold()

    if category == "Illness":
        return relationship in ILLNESS_RELATIONSHIPS and vital_status == "alive"
    if category == "Death":
        return (
            relationship in DEATH_RELATIONSHIPS
            and vital_status == "alive"
        )
    return False


def allowed_relationships_for_category(category: str) -> set[str]:
    if category == "Illness":
        return ILLNESS_RELATIONSHIPS
    if category == "Death":
        return DEATH_RELATIONSHIPS
    return set()
