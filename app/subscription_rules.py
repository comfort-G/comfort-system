from datetime import date


MONTHLY_SUBSCRIPTION_TARGET = 20_000
INACTIVE_ARREARS_THRESHOLD = 50_000


def calculate_subscription_arrears(
    current_year_contributions: float, today: date
) -> tuple[float, int]:
    expected_contributions = today.month * MONTHLY_SUBSCRIPTION_TARGET
    arrears = max(0.0, expected_contributions - current_year_contributions)
    return arrears, expected_contributions


def is_inactive_by_subscription_arrears(arrears: float) -> bool:
    return arrears > INACTIVE_ARREARS_THRESHOLD
