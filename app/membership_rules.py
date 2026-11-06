from datetime import date, datetime


FULL_MEMBER_WELFARE_THRESHOLD = 100_000
PROBATION_PERIOD_DAYS = 60


def calculate_membership_tier(
    joined_date: date | datetime | str | None,
    total_welfare: float,
    today: date | None = None,
) -> tuple[str, int]:
    reference_date = today or date.today()
    if isinstance(joined_date, datetime):
        joined_date = joined_date.date()
    elif isinstance(joined_date, str):
        try:
            joined_date = date.fromisoformat(joined_date[:10])
        except ValueError:
            joined_date = None

    if not isinstance(joined_date, date):
        joined_date = reference_date

    days_in_group = (reference_date - joined_date).days
    if days_in_group < PROBATION_PERIOD_DAYS:
        return "Probation member", days_in_group
    if total_welfare >= FULL_MEMBER_WELFARE_THRESHOLD:
        return "Full member", days_in_group
    return "Partial member", days_in_group


def is_probationary_member(
    joined_date: date | datetime | str | None,
    today: date | None = None,
) -> bool:
    membership_tier, _ = calculate_membership_tier(
        joined_date,
        total_welfare=0,
        today=today,
    )
    return membership_tier == "Probation member"
