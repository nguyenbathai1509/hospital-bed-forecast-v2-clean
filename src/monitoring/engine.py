from __future__ import annotations

from datetime import date
import math

import numpy as np

from src.monitoring.contracts import CapacityEventMetrics, MatchValues
from src.training.metrics import RegressionMetrics, compute_regression_metrics


def actual_availability_status(
    *,
    target_date: date,
    latest_actual_date: date | None,
) -> str:
    """Return whether a target date is mature enough to expect an Actual row.

    Future Actual is never fabricated. If the department's CLEAN history has not
    reached target_date, the Official must remain WAITING_FOR_ACTUAL.
    """

    if latest_actual_date is None or target_date > latest_actual_date:
        return "WAITING_FOR_ACTUAL"

    return "ELIGIBLE"


def build_match_values(
    *,
    actual_occupied_beds: int,
    prediction_raw: float,
    prediction_rounded: int,
) -> MatchValues:
    """Create one Official-vs-Actual error record.

    V2 sign convention:
        error = actual - prediction

    Positive error/bias means underprediction; negative means overprediction.
    """

    actual = int(actual_occupied_beds)
    rounded = int(prediction_rounded)
    raw = float(prediction_raw)

    if actual < 0:
        raise ValueError("actual_occupied_beds must be >= 0")

    if rounded < 0:
        raise ValueError("prediction_rounded must be >= 0")

    if not math.isfinite(raw):
        raise ValueError("prediction_raw must be finite")

    error_raw = float(actual - raw)
    error_rounded = int(actual - rounded)

    return MatchValues(
        actual_occupied_beds=actual,
        prediction_raw=raw,
        prediction_rounded=rounded,
        error_raw=error_raw,
        abs_error_raw=abs(error_raw),
        error_rounded=error_rounded,
        abs_error_rounded=abs(error_rounded),
        underpredicted=(raw < actual),
        overpredicted=(raw > actual),
        exact_rounded=(rounded == actual),
    )


def compute_production_metrics(
    *,
    actual_values,
    prediction_raw_values,
) -> RegressionMetrics:
    """Compute Production model-quality metrics from immutable raw Official values."""

    return compute_regression_metrics(
        actual_values,
        prediction_raw_values,
    )


def compute_capacity_event_metrics(
    *,
    actual_values,
    planned_beds_values,
    predicted_capacity_alert_values,
) -> CapacityEventMetrics:
    """Evaluate the optional capacity-alert event contract.

    Actual capacity event:
        actual_occupied_beds > planned_beds

    Predicted capacity event:
        Official.capacity_alert == True

    planned_beds remains a capacity reference only; it is never a prediction cap.
    """

    actual = np.asarray(actual_values, dtype=float).reshape(-1)
    planned = np.asarray(planned_beds_values, dtype=float).reshape(-1)
    predicted = np.asarray(predicted_capacity_alert_values, dtype=bool).reshape(-1)

    if not (actual.size == planned.size == predicted.size):
        raise ValueError(
            "actual_values, planned_beds_values and predicted_capacity_alert_values "
            "must have equal length"
        )

    if actual.size == 0:
        raise ValueError("Cannot compute capacity-event metrics on zero rows")

    if not np.isfinite(actual).all() or not np.isfinite(planned).all():
        raise ValueError("Capacity-event metrics require finite numeric values")

    if np.any(actual < 0) or np.any(planned <= 0):
        raise ValueError("Actual must be >= 0 and planned_beds must be > 0")

    actual_event = actual > planned

    tp = int(np.sum(predicted & actual_event))
    fp = int(np.sum(predicted & ~actual_event))
    fn = int(np.sum(~predicted & actual_event))
    tn = int(np.sum(~predicted & ~actual_event))

    precision_denom = tp + fp
    recall_denom = tp + fn

    precision = None if precision_denom == 0 else float(tp / precision_denom)
    recall = None if recall_denom == 0 else float(tp / recall_denom)
    accuracy = float((tp + tn) / actual.size)

    return CapacityEventMetrics(
        sample_count=int(actual.size),
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        precision=precision,
        recall=recall,
        accuracy=accuracy,
    )


def monitoring_run_status(
    *,
    official_total_count: int,
    matched_total_count: int,
    waiting_for_actual_count: int,
    missing_actual_count: int,
) -> str:
    """Derive an auditable monitoring-cycle status from mutually exclusive counts."""

    counts = (
        int(official_total_count),
        int(matched_total_count),
        int(waiting_for_actual_count),
        int(missing_actual_count),
    )

    if any(value < 0 for value in counts):
        raise ValueError("Monitoring counts must be non-negative")

    total, matched, waiting, missing = counts

    if matched + waiting + missing != total:
        raise ValueError(
            "matched + waiting + missing must equal official_total_count"
        )

    if total == 0:
        return "NO_OFFICIALS"

    if matched == total:
        return "COMPLETED"

    if waiting == total:
        return "WAITING_FOR_ACTUAL"

    return "PARTIAL"