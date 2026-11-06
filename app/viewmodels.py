from __future__ import annotations

from collections import defaultdict
from typing import Any


def department_label(row: dict[str, Any]) -> str:
    return f"{row['department_id']} - {row['department_name']}"


def latest_completed_training_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    completed = [row for row in runs if row.get("status") == "COMPLETED"]
    if not completed:
        return None
    return max(completed, key=lambda row: str(row.get("completed_at") or ""))


def production_by_horizon(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["horizon"]): row
        for row in payload.get("horizons", [])
        if row.get("horizon") in (1, 3)
    }


def official_index(rows: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    return {
        (int(row["department_id"]), int(row["horizon"])): row
        for row in rows
    }


def summarize_dashboard(
    *,
    data_status: dict[str, Any],
    pipeline_runs: list[dict[str, Any]],
    training_runs: list[dict[str, Any]],
    production: dict[str, Any],
    officials: list[dict[str, Any]],
    departments: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_pipeline = pipeline_runs[0] if pipeline_runs else None
    latest_training = latest_completed_training_run(training_runs)
    prod = production_by_horizon(production)
    official_map = official_index(officials)

    official_states: list[dict[str, Any]] = []
    for department in departments:
        department_id = int(department["department_id"])
        for horizon in (1, 3):
            official = official_map.get((department_id, horizon))
            official_states.append(
                {
                    "department_id": department_id,
                    "department_name": department["department_name"],
                    "horizon": horizon,
                    "status": "OFFICIAL" if official else "PENDING",
                    "prediction_rounded": (
                        None if official is None else official.get("prediction_rounded")
                    ),
                }
            )

    return {
        "business_date": data_status.get("business_date"),
        "data_status": data_status.get("status"),
        "latest_pipeline": latest_pipeline,
        "latest_training": latest_training,
        "production_h1": prod.get(1, {}).get("active"),
        "production_h3": prod.get(3, {}).get("active"),
        "recommendation_h1": prod.get(1, {}).get("recommendation"),
        "recommendation_h3": prod.get(3, {}).get("recommendation"),
        "official_states": official_states,
        "normal_change_quota_used": bool(production.get("normal_change_quota_used")),
    }


def candidate_rows_for_horizon(
    candidates: list[dict[str, Any]], horizon: int
) -> list[dict[str, Any]]:
    rows = [row for row in candidates if int(row.get("horizon", 0)) == horizon]
    return sorted(rows, key=lambda row: float(row.get("mae", float("inf"))))



def enrich_department_metrics(
    metrics: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join candidate metadata needed by the UI without inventing metrics.

    FastAPI intentionally returns department metrics keyed by candidate_id. Horizon and
    model_family live on the candidate rows, so the presentation layer joins those two
    read models in memory.
    """
    candidate_map = {row["candidate_id"]: row for row in candidates}
    enriched: list[dict[str, Any]] = []
    for metric in metrics:
        candidate = candidate_map.get(metric.get("candidate_id"), {})
        row = dict(metric)
        row["horizon"] = candidate.get("horizon")
        row["model_family"] = candidate.get("model_family")
        enriched.append(row)
    return enriched

def department_mae_matrix(
    metrics: list[dict[str, Any]], horizon: int
) -> list[dict[str, Any]]:
    filtered = [row for row in metrics if int(row.get("horizon", 0)) == horizon]
    grouped: dict[int, dict[str, Any]] = defaultdict(dict)
    for row in filtered:
        department_id = int(row["department_id"])
        grouped[department_id]["department_id"] = department_id
        grouped[department_id][str(row["model_family"])] = row.get("mae")
    return [grouped[key] for key in sorted(grouped)]


def format_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}%"


TRAINING_METRICS: dict[str, dict[str, Any]] = {
    "MAE": {"key": "mae", "better": "lower", "scale": 1.0, "unit": "beds"},
    "RMSE": {"key": "rmse", "better": "lower", "scale": 1.0, "unit": "beds"},
    "WAPE": {"key": "wape", "better": "lower", "scale": 1.0, "unit": "%"},
    "R²": {"key": "r2", "better": "higher", "scale": 1.0, "unit": ""},
    "Bias": {"key": "bias", "better": "zero", "scale": 1.0, "unit": "beds"},
    "P90 Absolute Error": {"key": "p90_abs_error", "better": "lower", "scale": 1.0, "unit": "beds"},
    "Max Absolute Error": {"key": "max_abs_error", "better": "lower", "scale": 1.0, "unit": "beds"},
    "Within ±2 Rate": {"key": "within_2_rate", "better": "higher", "scale": 100.0, "unit": "%"},
    "Underprediction Rate": {"key": "underprediction_rate", "better": "lower", "scale": 100.0, "unit": "%"},
    "Underprediction MAE": {"key": "underprediction_mae", "better": "lower", "scale": 1.0, "unit": "beds"},
}


def metric_comparison_rows(
    rows: list[dict[str, Any]],
    *,
    horizon: int,
    metric_key: str,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if int(row.get("horizon") or 0) != horizon:
            continue
        if department_id is not None and int(row.get("department_id") or 0) != department_id:
            continue
        value = row.get(metric_key)
        if value is None:
            continue
        filtered.append(
            {
                "model_family": row.get("model_family"),
                "value": value,
            }
        )
    return sorted(filtered, key=lambda row: str(row.get("model_family")))


def evaluation_chart_frame(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "target_date": row.get("target_date"),
            "actual": row.get("actual_occupied_beds"),
            "predicted": row.get("prediction_raw"),
            "residual": row.get("residual"),
            "zero": 0.0,
        }
        for row in rows
    ]