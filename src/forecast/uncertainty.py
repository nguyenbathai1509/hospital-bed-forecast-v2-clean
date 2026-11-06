"""Advisory empirical error bands; no model fitting or forecast writes."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math


METHOD = "official-errors-90-v1"
MIN_SAMPLES = 30
LOOKBACK_DAYS = 90
BUSINESS_TZ = timezone(timedelta(hours=7))


def utc(value: datetime) -> datetime:
    # SQL Server timestamps in this project are UTC, without an offset.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def business_day_end(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, BUSINESS_TZ).astimezone(timezone.utc)


def build_uncertainty(
    *, candidate_id: str, department_id: int, horizon: int, origin_date: date,
    prediction_raw: float, training_data_end: date, rows: list[dict],
    now: datetime, forecast_created_at: datetime | None = None,
) -> dict:
    """Calibrate only from genuinely earlier official forecasts of this artifact.

    Order-statistic radius follows the split-conformal recipe. Time dependence,
    drift and selective issuance mean NO coverage guarantee is claimed here.
    Missing historical revisions are excluded, never reconstructed from the future.
    """
    if horizon not in (1, 3) or not math.isfinite(prediction_raw):
        raise ValueError("Invalid horizon or non-finite point prediction")
    if origin_date > utc(now).astimezone(BUSINESS_TZ).date():
        raise ValueError("Ngày dữ liệu không được nằm trong tương lai.")
    as_of = min(utc(now), business_day_end(origin_date))
    if forecast_created_at is not None:
        as_of = min(as_of, utc(forecast_created_at))
    start = origin_date - timedelta(days=min(LOOKBACK_DAYS - 1, origin_date.toordinal() - 1))
    result = {
        "status": "INSUFFICIENT_DATA", "method": METHOD,
        "candidate_id": candidate_id, "department_id": department_id, "horizon": horizon,
        "origin_date": origin_date, "prediction_raw": prediction_raw,
        "nominal_coverage": 0.90, "coverage_guaranteed": False,
        "persisted": False, "sample_count": 0, "minimum_samples": MIN_SAMPLES,
        "lookback_days": LOOKBACK_DAYS, "as_of": as_of,
        "calibration_start": None, "calibration_end": None,
        "radius": None, "lower_beds": None, "upper_beds": None,
        "evidence_sha256": None,
        "reason": "Chưa đủ 30 dự báo chính thức hợp lệ của cùng mô hình, khoa và mốc dự báo.",
    }
    if origin_date < training_data_end:
        result["reason"] = "Ngày dự báo nằm trước khi kết thúc dữ liệu huấn luyện của mô hình."
        return result
    selected = []
    for row in rows:
        if (row["candidate_id"] != candidate_id or int(row["department_id"]) != department_id
                or int(row["horizon"]) != horizon):
            continue
        target, origin = row["target_date"], row["origin_date"]
        if target > as_of.astimezone(BUSINESS_TZ).date():
            continue
        if not (start <= target <= origin_date and training_data_end <= origin < origin_date):
            continue
        if (target - origin).days != horizon:
            raise ValueError("Invalid calibration origin/target dates")
        issued, refreshed = utc(row["issued_at"]), utc(row["last_refreshed_at"])
        # Exclude forecasts backfilled after the original prediction day, and
        # matches/revisions that had not been recorded by the requested as-of time.
        if issued >= business_day_end(origin) or issued >= as_of or refreshed >= as_of:
            continue
        if row["actual_quality_flag"] != "PASS":
            continue
        actual, predicted = float(row["actual_occupied_beds"]), float(row["prediction_raw"])
        if not math.isfinite(actual) or actual < 0 or not math.isfinite(predicted):
            raise ValueError("Invalid calibration values")
        selected.append({**row, "abs_error": abs(actual - max(0.0, predicted))})
    selected.sort(key=lambda r: (r["target_date"], r["official_id"]))
    if len({r["target_date"] for r in selected}) != len(selected):
        raise ValueError("Duplicate calibration target dates")
    result["sample_count"] = len(selected)
    if selected:
        result.update(calibration_start=selected[0]["target_date"], calibration_end=selected[-1]["target_date"])
    if len(selected) < MIN_SAMPLES:
        return result
    # ceil((n+1)*.9), computed with integer arithmetic (no interpolation).
    rank = (9 * (len(selected) + 1) + 9) // 10
    radius = sorted(r["abs_error"] for r in selected)[rank - 1]
    center = max(0.0, prediction_raw)
    lower, upper = max(0.0, center - radius), center + radius
    if not math.isfinite(upper):
        raise ValueError("Non-finite uncertainty bound")
    proof = json.dumps(selected, default=str, sort_keys=True, allow_nan=False)
    result.update(
        status="AVAILABLE", radius=radius,
        lower_beds=math.floor(lower), upper_beds=math.ceil(upper),
        evidence_sha256=hashlib.sha256(proof.encode()).hexdigest(),
        reason="Khoảng tham khảo từ sai số lịch sử, mức bao phủ mục tiêu 90%; không bảo đảm 90% cho chuỗi thời gian.",
    )
    return result
