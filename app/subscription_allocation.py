from datetime import date
from decimal import Decimal
from typing import Mapping

from app.subscription_rules import MONTHLY_SUBSCRIPTION_TARGET


MONTHLY_TARGET = Decimal(MONTHLY_SUBSCRIPTION_TARGET)
MAX_ALLOCATION_MONTHS = 1200


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def allocate_subscription_payment(
    amount: Decimal,
    paid_by_month: Mapping[date, Decimal],
    start_month: date,
) -> list[dict[str, Decimal | date]]:
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Subscription payment amount must be greater than zero.")
    if amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("Subscription payment cannot have more than two decimals.")

    remaining = amount
    billing_month = month_start(start_month)
    allocations: list[dict[str, Decimal | date]] = []
    checked_months = 0

    while remaining > 0 and checked_months < MAX_ALLOCATION_MONTHS:
        paid = max(Decimal("0"), paid_by_month.get(billing_month, Decimal("0")))
        due = max(Decimal("0"), MONTHLY_TARGET - paid)
        if due:
            allocated = min(remaining, due)
            allocations.append(
                {"billing_month": billing_month, "amount": allocated}
            )
            remaining -= allocated
        billing_month = next_month(billing_month)
        checked_months += 1

    if remaining > 0:
        raise ValueError(
            "This amount spans too many months to allocate safely. "
            "Verify the amount and contact system support."
        )
    return allocations
