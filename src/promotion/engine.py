from __future__ import annotations

from datetime import date, timedelta


def validate_horizons(horizons) -> tuple[int, ...]:
    values = tuple(dict.fromkeys(int(value) for value in horizons))

    if not values:
        raise ValueError("At least one horizon is required")

    invalid = [value for value in values if value not in {1, 3}]

    if invalid:
        raise ValueError(
            f"Unsupported horizons: {invalid}; expected only 1 and/or 3"
        )

    return values


def resolve_effect(
    *,
    business_date: date,
    daily_lock_present: bool,
) -> tuple[str, date]:
    if daily_lock_present:
        return (
            "NEXT_CYCLE",
            business_date + timedelta(days=1),
        )

    return (
        "IMMEDIATE",
        business_date,
    )