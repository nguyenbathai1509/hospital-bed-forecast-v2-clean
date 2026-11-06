from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.db.engine import create_sql_engine
from src.monitoring.engine import (
    actual_availability_status,
    build_match_values,
    compute_capacity_event_metrics,
    compute_production_metrics,
    monitoring_run_status,
)
from src.monitoring.repository import MonitoringRepository


def _monitoring_run_id(pipeline_run_id: str) -> str:
    return f"MON_{pipeline_run_id}"


def _match_row_payload(context: dict) -> dict:
    values = build_match_values(
        actual_occupied_beds=int(context["actual_occupied_beds"]),
        prediction_raw=float(context["prediction_raw"]),
        prediction_rounded=int(context["prediction_rounded"]),
    )

    planned_beds = int(context["planned_beds"])

    actual_capacity_exceeded = (
        int(context["actual_occupied_beds"])
        > planned_beds
    )

    predicted_capacity_alert = bool(
        context["capacity_alert"]
    )

    return {
        "official_id": context["official_id"],
        "origin_date": context["origin_date"],
        "target_date": context["target_date"],
        "department_id": int(
            context["department_id"]
        ),
        "horizon": int(
            context["horizon"]
        ),
        "candidate_id": context["candidate_id"],
        "planned_beds": planned_beds,
        "prediction_raw": float(
            context["prediction_raw"]
        ),
        "prediction_rounded": int(
            context["prediction_rounded"]
        ),
        "capacity_alert": (
            predicted_capacity_alert
        ),
        "actual_occupied_beds": int(
            context["actual_occupied_beds"]
        ),
        "actual_quality_flag": (
            context["actual_quality_flag"]
        ),
        "actual_source_revision_no": int(
            context["actual_source_revision_no"]
        ),
        "error_raw": values.error_raw,
        "abs_error_raw": values.abs_error_raw,
        "error_rounded": values.error_rounded,
        "abs_error_rounded": (
            values.abs_error_rounded
        ),
        "underpredicted": values.underpredicted,
        "overpredicted": values.overpredicted,
        "exact_rounded": values.exact_rounded,
        "actual_capacity_exceeded": (
            actual_capacity_exceeded
        ),
        "capacity_alert_correct": (
            predicted_capacity_alert
            == actual_capacity_exceeded
        ),
    }


def _same_actual_evidence(
    existing: dict,
    payload: dict,
) -> bool:
    return (
        int(existing["actual_occupied_beds"])
        == int(payload["actual_occupied_beds"])
        and str(existing["actual_quality_flag"])
        == str(payload["actual_quality_flag"])
        and int(existing["actual_source_revision_no"])
        == int(payload["actual_source_revision_no"])
    )


def run_actual_matching() -> dict:
    """Attach CLEAN Actual only to immutable Official Forecast evidence."""

    engine = create_sql_engine()

    inserted = 0
    updated = 0
    unchanged = 0
    waiting = 0
    missing = 0

    with engine.begin() as conn:
        repo = MonitoringRepository(
            conn
        )

        rows = (
            repo.official_actual_context_rows()
        )

        latest_actual_date = (
            repo.latest_actual_date()
        )

        for context in rows:
            if (
                context[
                    "actual_occupied_beds"
                ]
                is not None
            ):
                payload = (
                    _match_row_payload(
                        context
                    )
                )

                existing = (
                    repo.existing_match(
                        context[
                            "official_id"
                        ]
                    )
                )

                if existing is None:
                    repo.insert_match(
                        payload
                    )
                    inserted += 1

                elif _same_actual_evidence(
                    existing,
                    payload,
                ):
                    unchanged += 1

                else:
                    repo.update_match(
                        payload
                    )
                    updated += 1

                continue

            availability = (
                actual_availability_status(
                    target_date=(
                        context[
                            "target_date"
                        ]
                    ),
                    latest_actual_date=(
                        context[
                            "department_latest_actual_date"
                        ]
                    ),
                )
            )

            if (
                availability
                == "WAITING_FOR_ACTUAL"
            ):
                waiting += 1
            else:
                missing += 1

        matched_total = (
            repo.match_count()
        )

    official_total = len(
        rows
    )

    return {
        "status": monitoring_run_status(
            official_total_count=(
                official_total
            ),
            matched_total_count=(
                matched_total
            ),
            waiting_for_actual_count=(
                waiting
            ),
            missing_actual_count=(
                missing
            ),
        ),
        "latest_actual_date": (
            None
            if latest_actual_date is None
            else str(
                latest_actual_date
            )
        ),
        "official_total_count": (
            official_total
        ),
        "matched_total_count": (
            matched_total
        ),
        "inserted_match_count": (
            inserted
        ),
        "updated_match_count": (
            updated
        ),
        "unchanged_match_count": (
            unchanged
        ),
        "waiting_for_actual_count": (
            waiting
        ),
        "missing_actual_count": (
            missing
        ),
    }


def _metric_payload(
    *,
    monitoring_run_id: str,
    metric_scope: str,
    horizon: int,
    candidate_id: str,
    department_id: int | None,
    rows: list[dict],
) -> dict:
    metrics = (
        compute_production_metrics(
            actual_values=[
                row[
                    "actual_occupied_beds"
                ]
                for row in rows
            ],
            prediction_raw_values=[
                row[
                    "prediction_raw"
                ]
                for row in rows
            ],
        )
    )

    capacity = (
        compute_capacity_event_metrics(
            actual_values=[
                row[
                    "actual_occupied_beds"
                ]
                for row in rows
            ],
            planned_beds_values=[
                row[
                    "planned_beds"
                ]
                for row in rows
            ],
            predicted_capacity_alert_values=[
                row[
                    "capacity_alert"
                ]
                for row in rows
            ],
        )
    )

    return {
        "monitoring_run_id": (
            monitoring_run_id
        ),
        "metric_scope": (
            metric_scope
        ),
        "horizon": horizon,
        "candidate_id": (
            candidate_id
        ),
        "department_id": (
            department_id
        ),
        "sample_count": (
            metrics.sample_count
        ),
        "through_target_date": max(
            row["target_date"]
            for row in rows
        ),
        "mae": metrics.mae,
        "rmse": metrics.rmse,
        "wape": metrics.wape,
        "r2": metrics.r2,
        "bias": metrics.bias,
        "p90_abs_error": (
            metrics.p90_abs_error
        ),
        "max_abs_error": (
            metrics.max_abs_error
        ),
        "within_2_rate": (
            metrics.within_2_rate
        ),
        "underprediction_rate": (
            metrics.underprediction_rate
        ),
        "underprediction_mae": (
            metrics.underprediction_mae
        ),
        "capacity_event_tp": (
            capacity.true_positive
        ),
        "capacity_event_fp": (
            capacity.false_positive
        ),
        "capacity_event_fn": (
            capacity.false_negative
        ),
        "capacity_event_tn": (
            capacity.true_negative
        ),
        "capacity_event_precision": (
            capacity.precision
        ),
        "capacity_event_recall": (
            capacity.recall
        ),
        "capacity_event_accuracy": (
            capacity.accuracy
        ),
    }


def run_production_monitoring(
    *,
    pipeline_run_id: str,
    business_date: date,
) -> dict:
    """Create an auditable cumulative Production-monitoring snapshot.

    Only rows in dbo.official_actual_matches are used, so Preview, Draft,
    Recommended and Custom forecasts are structurally excluded.
    """

    engine = create_sql_engine()

    monitoring_run_id = (
        _monitoring_run_id(
            pipeline_run_id
        )
    )

    with engine.begin() as conn:
        repo = MonitoringRepository(
            conn
        )

        contexts = (
            repo.official_actual_context_rows()
        )

        latest_actual_date = (
            repo.latest_actual_date()
        )

        waiting = 0
        missing = 0

        for context in contexts:
            if (
                context[
                    "actual_occupied_beds"
                ]
                is not None
            ):
                continue

            availability = (
                actual_availability_status(
                    target_date=(
                        context[
                            "target_date"
                        ]
                    ),
                    latest_actual_date=(
                        context[
                            "department_latest_actual_date"
                        ]
                    ),
                )
            )

            if (
                availability
                == "WAITING_FOR_ACTUAL"
            ):
                waiting += 1
            else:
                missing += 1

        matches = (
            repo.match_rows()
        )

        matched_total = len(
            matches
        )

        official_total = len(
            contexts
        )

        status = (
            monitoring_run_status(
                official_total_count=(
                    official_total
                ),
                matched_total_count=(
                    matched_total
                ),
                waiting_for_actual_count=(
                    waiting
                ),
                missing_actual_count=(
                    missing
                ),
            )
        )

        repo.reset_monitoring_run(
            monitoring_run_id=(
                monitoring_run_id
            ),
            pipeline_run_id=(
                pipeline_run_id
            ),
            business_date=(
                business_date
            ),
            latest_actual_date=(
                latest_actual_date
            ),
            status=status,
            official_total_count=(
                official_total
            ),
            matched_total_count=(
                matched_total
            ),
            waiting_for_actual_count=(
                waiting
            ),
            missing_actual_count=(
                missing
            ),
        )

        actual_monitoring_run_id = (
            repo.monitoring_run_id_for_pipeline(
                pipeline_run_id
            )
        )

        if (
            actual_monitoring_run_id
            is None
        ):
            raise RuntimeError(
                "Monitoring run was not persisted "
                f"for pipeline_run_id={pipeline_run_id}"
            )

        monitoring_run_id = str(
            actual_monitoring_run_id
        )

        horizon_groups: dict[
            tuple[int, str],
            list[dict],
        ] = defaultdict(list)

        department_groups: dict[
            tuple[int, str, int],
            list[dict],
        ] = defaultdict(list)

        for row in matches:
            horizon = int(
                row["horizon"]
            )

            candidate_id = str(
                row["candidate_id"]
            )

            department_id = int(
                row["department_id"]
            )

            horizon_groups[
                (
                    horizon,
                    candidate_id,
                )
            ].append(
                row
            )

            department_groups[
                (
                    horizon,
                    candidate_id,
                    department_id,
                )
            ].append(
                row
            )

        metric_rows: list[
            dict
        ] = []

        for (
            horizon,
            candidate_id,
        ), group_rows in sorted(
            horizon_groups.items()
        ):
            metric_rows.append(
                _metric_payload(
                    monitoring_run_id=(
                        monitoring_run_id
                    ),
                    metric_scope=(
                        "HORIZON"
                    ),
                    horizon=horizon,
                    candidate_id=(
                        candidate_id
                    ),
                    department_id=None,
                    rows=group_rows,
                )
            )

        for (
            horizon,
            candidate_id,
            department_id,
        ), group_rows in sorted(
            department_groups.items()
        ):
            metric_rows.append(
                _metric_payload(
                    monitoring_run_id=(
                        monitoring_run_id
                    ),
                    metric_scope=(
                        "DEPARTMENT"
                    ),
                    horizon=horizon,
                    candidate_id=(
                        candidate_id
                    ),
                    department_id=(
                        department_id
                    ),
                    rows=group_rows,
                )
            )

        for row in metric_rows:
            repo.insert_metric(
                row
            )

        repo.finish_monitoring_run_metric_count(
            monitoring_run_id=(
                monitoring_run_id
            ),
            metric_row_count=len(
                metric_rows
            ),
        )

    return {
        "status": status,
        "monitoring_run_id": (
            monitoring_run_id
        ),
        "pipeline_run_id": (
            pipeline_run_id
        ),
        "business_date": str(
            business_date
        ),
        "latest_actual_date": (
            None
            if latest_actual_date is None
            else str(
                latest_actual_date
            )
        ),
        "official_total_count": (
            official_total
        ),
        "matched_total_count": (
            matched_total
        ),
        "waiting_for_actual_count": (
            waiting
        ),
        "missing_actual_count": (
            missing
        ),
        "metric_row_count": len(
            metric_rows
        ),
        "metrics": metric_rows,
    }


def run_monitoring_cycle(
    *,
    pipeline_run_id: str | None = None,
) -> dict:
    """Manual/recovery entry point using an existing pipeline run."""

    engine = create_sql_engine()

    with engine.connect() as conn:
        repo = MonitoringRepository(
            conn
        )

        if pipeline_run_id is None:
            pipeline = (
                repo.latest_data_ready_pipeline()
            )

            if pipeline is None:
                raise RuntimeError(
                    "No DATA_READY pipeline run exists"
                )

            pipeline_run_id = str(
                pipeline["run_id"]
            )

            business_date = (
                pipeline[
                    "business_date"
                ]
            )

        else:
            from sqlalchemy import text

            pipeline = conn.execute(
                text(
                    """
                    SELECT
                        run_id,
                        business_date,
                        status
                    FROM dbo.pipeline_runs
                    WHERE run_id=:run_id
                    """
                ),
                {
                    "run_id": (
                        pipeline_run_id
                    )
                },
            ).mappings().first()

            if pipeline is None:
                raise RuntimeError(
                    "Unknown pipeline_run_id="
                    f"{pipeline_run_id}"
                )

            pipeline_status = str(
                pipeline["status"]
            )

            if pipeline_status != "DATA_READY":
                raise RuntimeError(
                    "Monitoring recovery requires "
                    "a DATA_READY pipeline run; "
                    f"pipeline_run_id={pipeline_run_id}, "
                    f"status={pipeline_status}"
                )

            business_date = (
                pipeline[
                    "business_date"
                ]
            )

    if business_date is None:
        raise RuntimeError(
            "Pipeline run has no business_date"
        )

    matching = (
        run_actual_matching()
    )

    monitoring = (
        run_production_monitoring(
            pipeline_run_id=(
                pipeline_run_id
            ),
            business_date=(
                business_date
            ),
        )
    )

    return {
        "status": (
            monitoring["status"]
        ),
        "actual_matching": (
            matching
        ),
        "production_monitoring": (
            monitoring
        ),
    }