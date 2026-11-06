from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


MONTHLY_LOAN_INTEREST_RATE = Decimal("0.10")
MONEY_PRECISION = Decimal("0.01")


def next_monthly_interest_due_date(reference_date: date) -> date:
    month = reference_date.month + 1
    year = reference_date.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(reference_date.day, 28, monthrange(year, month)[1])
    return date(year, month, day)


def calculate_monthly_loan_interest(principal_remaining: Decimal) -> Decimal:
    return (principal_remaining * MONTHLY_LOAN_INTEREST_RATE).quantize(
        MONEY_PRECISION,
        rounding=ROUND_HALF_UP,
    )
