from datetime import date

import pytest

from src.promotion.contracts import (
    PROMOTION_CONFIRMATION_PHRASE,
    ROLLBACK_CONFIRMATION_PHRASE,
)

from src.promotion.engine import (
    resolve_effect,
    validate_horizons,
)


def test_promotion_confirmation_phrases_are_explicit_and_distinct():
    assert (
        PROMOTION_CONFIRMATION_PHRASE
        == "I_CONFIRM_PROMOTION"
    )

    assert (
        ROLLBACK_CONFIRMATION_PHRASE
        == "I_CONFIRM_EMERGENCY_ROLLBACK"
    )

    assert (
        PROMOTION_CONFIRMATION_PHRASE
        != ROLLBACK_CONFIRMATION_PHRASE
    )


def test_no_daily_lock_means_immediate():
    effect, effective_from = (
        resolve_effect(
            business_date=date(
                2026,
                6,
                30,
            ),
            daily_lock_present=False,
        )
    )

    assert effect == "IMMEDIATE"

    assert (
        effective_from
        == date(
            2026,
            6,
            30,
        )
    )


def test_daily_lock_means_next_cycle():
    effect, effective_from = (
        resolve_effect(
            business_date=date(
                2026,
                6,
                30,
            ),
            daily_lock_present=True,
        )
    )

    assert (
        effect
        == "NEXT_CYCLE"
    )

    assert (
        effective_from
        == date(
            2026,
            7,
            1,
        )
    )


def test_horizon_validation_is_deduplicated_and_order_preserving():
    assert (
        validate_horizons(
            [
                1,
                3,
                1,
            ]
        )
        == (
            1,
            3,
        )
    )


def test_invalid_horizon_is_rejected():
    with pytest.raises(
        ValueError
    ):
        validate_horizons(
            [2]
        )