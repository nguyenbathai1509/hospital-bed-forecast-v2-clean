from datetime import date

import pytest

from src.monitoring.engine import (
    actual_availability_status,
    build_match_values,
    compute_capacity_event_metrics,
    compute_production_metrics,
    monitoring_run_status,
)


def test_future_target_waits_for_actual_instead_of_inventing_data():
    assert actual_availability_status(
        target_date=date(
            2026,
            7,
            1,
        ),
        latest_actual_date=date(
            2026,
            6,
            30,
        ),
    ) == "WAITING_FOR_ACTUAL"


def test_target_on_latest_clean_date_is_eligible():
    assert actual_availability_status(
        target_date=date(
            2026,
            6,
            30,
        ),
        latest_actual_date=date(
            2026,
            6,
            30,
        ),
    ) == "ELIGIBLE"


def test_match_error_sign_positive_means_underprediction():
    value = build_match_values(
        actual_occupied_beds=50,
        prediction_raw=47.5,
        prediction_rounded=48,
    )

    assert (
        value.error_raw
        == 2.5
    )

    assert (
        value.abs_error_raw
        == 2.5
    )

    assert (
        value.error_rounded
        == 2
    )

    assert (
        value.abs_error_rounded
        == 2
    )

    assert (
        value.underpredicted
        is True
    )

    assert (
        value.overpredicted
        is False
    )

    assert (
        value.exact_rounded
        is False
    )


def test_match_error_sign_negative_means_overprediction():
    value = build_match_values(
        actual_occupied_beds=40,
        prediction_raw=42.25,
        prediction_rounded=42,
    )

    assert (
        value.error_raw
        == -2.25
    )

    assert (
        value.error_rounded
        == -2
    )

    assert (
        value.underpredicted
        is False
    )

    assert (
        value.overpredicted
        is True
    )


def test_invalid_match_values_are_rejected():
    with pytest.raises(
        ValueError
    ):
        build_match_values(
            actual_occupied_beds=-1,
            prediction_raw=1.0,
            prediction_rounded=1,
        )

    with pytest.raises(
        ValueError
    ):
        build_match_values(
            actual_occupied_beds=1,
            prediction_raw=float(
                "nan"
            ),
            prediction_rounded=1,
        )


def test_production_metrics_use_raw_official_prediction_contract():
    metrics = compute_production_metrics(
        actual_values=[
            50,
            40,
        ],
        prediction_raw_values=[
            47.5,
            42.5,
        ],
    )

    assert (
        metrics.sample_count
        == 2
    )

    assert (
        metrics.mae
        == pytest.approx(
            2.5
        )
    )

    assert (
        metrics.rmse
        == pytest.approx(
            2.5
        )
    )

    assert (
        metrics.bias
        == pytest.approx(
            0.0
        )
    )

    assert (
        metrics.underprediction_rate
        == pytest.approx(
            0.5
        )
    )

    assert (
        metrics.within_2_rate
        == pytest.approx(
            0.0
        )
    )


def test_capacity_event_metrics_build_confusion_matrix():
    metrics = (
        compute_capacity_event_metrics(
            actual_values=[
                46,
                44,
                47,
                43,
            ],
            planned_beds_values=[
                45,
                45,
                45,
                45,
            ],
            predicted_capacity_alert_values=[
                True,
                True,
                False,
                False,
            ],
        )
    )

    assert (
        metrics.sample_count
        == 4
    )

    assert (
        metrics.true_positive
        == 1
    )

    assert (
        metrics.false_positive
        == 1
    )

    assert (
        metrics.false_negative
        == 1
    )

    assert (
        metrics.true_negative
        == 1
    )

    assert (
        metrics.precision
        == pytest.approx(
            0.5
        )
    )

    assert (
        metrics.recall
        == pytest.approx(
            0.5
        )
    )

    assert (
        metrics.accuracy
        == pytest.approx(
            0.5
        )
    )


def test_capacity_precision_and_recall_are_none_when_denominator_is_zero():
    metrics = (
        compute_capacity_event_metrics(
            actual_values=[
                40,
                41,
            ],
            planned_beds_values=[
                45,
                45,
            ],
            predicted_capacity_alert_values=[
                False,
                False,
            ],
        )
    )

    assert (
        metrics.precision
        is None
    )

    assert (
        metrics.recall
        is None
    )

    assert (
        metrics.accuracy
        == pytest.approx(
            1.0
        )
    )


def test_monitoring_status_no_officials():
    assert (
        monitoring_run_status(
            official_total_count=0,
            matched_total_count=0,
            waiting_for_actual_count=0,
            missing_actual_count=0,
        )
        == "NO_OFFICIALS"
    )


def test_monitoring_status_all_future_actual_is_waiting():
    assert (
        monitoring_run_status(
            official_total_count=4,
            matched_total_count=0,
            waiting_for_actual_count=4,
            missing_actual_count=0,
        )
        == "WAITING_FOR_ACTUAL"
    )


def test_monitoring_status_completed_or_partial_and_validates_counts():
    assert (
        monitoring_run_status(
            official_total_count=4,
            matched_total_count=4,
            waiting_for_actual_count=0,
            missing_actual_count=0,
        )
        == "COMPLETED"
    )

    assert (
        monitoring_run_status(
            official_total_count=4,
            matched_total_count=2,
            waiting_for_actual_count=2,
            missing_actual_count=0,
        )
        == "PARTIAL"
    )

    with pytest.raises(
        ValueError
    ):
        monitoring_run_status(
            official_total_count=4,
            matched_total_count=1,
            waiting_for_actual_count=1,
            missing_actual_count=0,
        )