from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.forecast.contracts import ForecastValue, VALID_PREVIEW_MODES


def normalize_preview_mode(mode: str) -> str:
    value = mode.strip().upper()

    if value not in VALID_PREVIEW_MODES:
        raise ValueError(
            f"Unsupported preview mode: {mode}; "
            "expected PRODUCTION, RECOMMENDED, or CUSTOM"
        )

    return value


def round_bed_prediction(value: float) -> int:
    """Round to an operational integer bed count without capping at capacity.

    The raw model output is preserved separately. Only the presentation/operational
    integer is floored at zero because occupied beds cannot be negative.
    """

    rounded = int(
        Decimal(str(float(value))).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )

    return max(0, rounded)


def build_forecast_value(
    *,
    prediction_raw: float,
    planned_beds: int,
) -> ForecastValue:
    if planned_beds <= 0:
        raise ValueError("planned_beds must be > 0")

    rounded = round_bed_prediction(
        prediction_raw
    )

    utilization = (
        float(prediction_raw)
        / float(planned_beds)
        * 100.0
    )

    excess = max(
        0,
        rounded - int(planned_beds),
    )

    return ForecastValue(
        prediction_raw=float(
            prediction_raw
        ),
        prediction_rounded=rounded,
        planned_beds=int(
            planned_beds
        ),
        predicted_utilization_pct=float(
            utilization
        ),
        capacity_alert=(
            rounded
            > int(planned_beds)
        ),
        capacity_excess_beds=excess,
    )