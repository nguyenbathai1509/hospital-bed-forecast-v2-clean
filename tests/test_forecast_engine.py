import math

import pytest

from src.forecast.engine import (
    build_forecast_value,
    normalize_preview_mode,
    round_bed_prediction,
)


def test_preview_modes_are_normalized():
    assert (
        normalize_preview_mode(
            "production"
        )
        == "PRODUCTION"
    )

    assert (
        normalize_preview_mode(
            " Recommended "
        )
        == "RECOMMENDED"
    )

    assert (
        normalize_preview_mode(
            "CUSTOM"
        )
        == "CUSTOM"
    )


def test_invalid_preview_mode_is_rejected():
    with pytest.raises(
        ValueError
    ):
        normalize_preview_mode(
            "OFFICIAL"
        )


def test_rounding_uses_half_up_for_bed_counts():
    assert (
        round_bed_prediction(
            42.49
        )
        == 42
    )

    assert (
        round_bed_prediction(
            42.50
        )
        == 43
    )


def test_operational_rounding_never_returns_negative_beds():
    assert (
        round_bed_prediction(
            -0.6
        )
        == 0
    )


def test_planned_beds_is_not_a_prediction_cap():
    value = build_forecast_value(
        prediction_raw=46.4,
        planned_beds=45,
    )

    assert (
        value.prediction_raw
        == 46.4
    )

    assert (
        value.prediction_rounded
        == 46
    )

    assert (
        value.capacity_alert
        is True
    )

    assert (
        value.capacity_excess_beds
        == 1
    )

    assert (
        value.prediction_rounded
        > value.planned_beds
    )


def test_capacity_alert_is_false_at_or_below_capacity():
    value = build_forecast_value(
        prediction_raw=44.6,
        planned_beds=45,
    )

    assert (
        value.prediction_rounded
        == 45
    )

    assert (
        value.capacity_alert
        is False
    )

    assert (
        value.capacity_excess_beds
        == 0
    )


def test_utilization_preserves_raw_prediction_precision():
    value = build_forecast_value(
        prediction_raw=45.5,
        planned_beds=45,
    )

    assert math.isclose(
        value.predicted_utilization_pct,
        45.5 / 45 * 100.0,
    )