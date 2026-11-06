from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection


class MonitoringRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def latest_actual_date(self) -> date | None:
        return self.conn.execute(
            text(
                """
                SELECT MAX(business_date)
                FROM dbo.clean_bed_daily
                """
            )
        ).scalar()

    def official_actual_context_rows(self) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    ofc.official_id,
                    ofc.origin_date,
                    ofc.target_date,
                    ofc.department_id,
                    ofc.horizon,
                    ofc.candidate_id,
                    ofc.planned_beds,
                    ofc.prediction_raw,
                    ofc.prediction_rounded,
                    ofc.capacity_alert,
                    cb.occupied_beds AS actual_occupied_beds,
                    cb.quality_flag AS actual_quality_flag,
                    cb.source_revision_no AS actual_source_revision_no,
                    dept_latest.latest_actual_date AS department_latest_actual_date
                FROM dbo.official_forecasts ofc
                OUTER APPLY (
                    SELECT MAX(c2.business_date) AS latest_actual_date
                    FROM dbo.clean_bed_daily c2
                    WHERE c2.department_id=ofc.department_id
                ) dept_latest
                LEFT JOIN dbo.clean_bed_daily cb
                    ON cb.business_date=ofc.target_date
                    AND cb.department_id=ofc.department_id
                ORDER BY ofc.target_date, ofc.horizon, ofc.department_id
                """
            )
        ).mappings().all()

        return [dict(row) for row in rows]

    def existing_match(self, official_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT *
                FROM dbo.official_actual_matches
                WHERE official_id=:official_id
                """
            ),
            {"official_id": official_id},
        ).mappings().first()

        return None if row is None else dict(row)

    def insert_match(self, row: dict) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.official_actual_matches
                (
                    official_id,
                    origin_date,
                    target_date,
                    department_id,
                    horizon,
                    candidate_id,
                    planned_beds,
                    prediction_raw,
                    prediction_rounded,
                    capacity_alert,
                    actual_occupied_beds,
                    actual_quality_flag,
                    actual_source_revision_no,
                    error_raw,
                    abs_error_raw,
                    error_rounded,
                    abs_error_rounded,
                    underpredicted,
                    overpredicted,
                    exact_rounded,
                    actual_capacity_exceeded,
                    capacity_alert_correct,
                    match_revision_no,
                    first_matched_at,
                    last_refreshed_at
                )
                VALUES
                (
                    :official_id,
                    :origin_date,
                    :target_date,
                    :department_id,
                    :horizon,
                    :candidate_id,
                    :planned_beds,
                    :prediction_raw,
                    :prediction_rounded,
                    :capacity_alert,
                    :actual_occupied_beds,
                    :actual_quality_flag,
                    :actual_source_revision_no,
                    :error_raw,
                    :abs_error_raw,
                    :error_rounded,
                    :abs_error_rounded,
                    :underpredicted,
                    :overpredicted,
                    :exact_rounded,
                    :actual_capacity_exceeded,
                    :capacity_alert_correct,
                    1,
                    SYSUTCDATETIME(),
                    SYSUTCDATETIME()
                )
                """
            ),
            row,
        )

    def update_match(self, row: dict) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.official_actual_matches
                SET
                    planned_beds=:planned_beds,
                    prediction_raw=:prediction_raw,
                    prediction_rounded=:prediction_rounded,
                    capacity_alert=:capacity_alert,
                    actual_occupied_beds=:actual_occupied_beds,
                    actual_quality_flag=:actual_quality_flag,
                    actual_source_revision_no=:actual_source_revision_no,
                    error_raw=:error_raw,
                    abs_error_raw=:abs_error_raw,
                    error_rounded=:error_rounded,
                    abs_error_rounded=:abs_error_rounded,
                    underpredicted=:underpredicted,
                    overpredicted=:overpredicted,
                    exact_rounded=:exact_rounded,
                    actual_capacity_exceeded=:actual_capacity_exceeded,
                    capacity_alert_correct=:capacity_alert_correct,
                    match_revision_no=match_revision_no+1,
                    last_refreshed_at=SYSUTCDATETIME()
                WHERE official_id=:official_id
                """
            ),
            row,
        )

    def match_count(self) -> int:
        return int(
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.official_actual_matches
                    """
                )
            ).scalar_one()
        )

    def match_rows(self) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    official_id,
                    origin_date,
                    target_date,
                    department_id,
                    horizon,
                    candidate_id,
                    planned_beds,
                    prediction_raw,
                    prediction_rounded,
                    capacity_alert,
                    actual_occupied_beds,
                    actual_quality_flag,
                    actual_source_revision_no,
                    error_raw,
                    abs_error_raw,
                    error_rounded,
                    abs_error_rounded,
                    underpredicted,
                    overpredicted,
                    exact_rounded,
                    actual_capacity_exceeded,
                    capacity_alert_correct,
                    match_revision_no,
                    first_matched_at,
                    last_refreshed_at
                FROM dbo.official_actual_matches
                ORDER BY horizon, candidate_id, department_id, target_date
                """
            )
        ).mappings().all()

        return [dict(row) for row in rows]

    def reset_monitoring_run(
        self,
        *,
        monitoring_run_id: str,
        pipeline_run_id: str,
        business_date: date,
        latest_actual_date: date | None,
        status: str,
        official_total_count: int,
        matched_total_count: int,
        waiting_for_actual_count: int,
        missing_actual_count: int,
    ) -> None:
        existing = self.conn.execute(
            text(
                """
                SELECT monitoring_run_id
                FROM dbo.production_monitoring_runs
                WHERE pipeline_run_id=:pipeline_run_id
                """
            ),
            {"pipeline_run_id": pipeline_run_id},
        ).scalar()

        if existing is None:
            self.conn.execute(
                text(
                    """
                    INSERT INTO dbo.production_monitoring_runs
                    (
                        monitoring_run_id,
                        pipeline_run_id,
                        business_date,
                        latest_actual_date,
                        status,
                        official_total_count,
                        matched_total_count,
                        waiting_for_actual_count,
                        missing_actual_count,
                        metric_row_count,
                        started_at,
                        completed_at
                    )
                    VALUES
                    (
                        :monitoring_run_id,
                        :pipeline_run_id,
                        :business_date,
                        :latest_actual_date,
                        :status,
                        :official_total_count,
                        :matched_total_count,
                        :waiting_for_actual_count,
                        :missing_actual_count,
                        0,
                        SYSUTCDATETIME(),
                        SYSUTCDATETIME()
                    )
                    """
                ),
                {
                    "monitoring_run_id": monitoring_run_id,
                    "pipeline_run_id": pipeline_run_id,
                    "business_date": business_date,
                    "latest_actual_date": latest_actual_date,
                    "status": status,
                    "official_total_count": official_total_count,
                    "matched_total_count": matched_total_count,
                    "waiting_for_actual_count": waiting_for_actual_count,
                    "missing_actual_count": missing_actual_count,
                },
            )
        else:
            monitoring_run_id = str(existing)

            self.conn.execute(
                text(
                    """
                    DELETE FROM dbo.production_monitoring_metrics
                    WHERE monitoring_run_id=:monitoring_run_id
                    """
                ),
                {"monitoring_run_id": monitoring_run_id},
            )

            self.conn.execute(
                text(
                    """
                    UPDATE dbo.production_monitoring_runs
                    SET
                        business_date=:business_date,
                        latest_actual_date=:latest_actual_date,
                        status=:status,
                        official_total_count=:official_total_count,
                        matched_total_count=:matched_total_count,
                        waiting_for_actual_count=:waiting_for_actual_count,
                        missing_actual_count=:missing_actual_count,
                        metric_row_count=0,
                        completed_at=SYSUTCDATETIME()
                    WHERE monitoring_run_id=:monitoring_run_id
                    """
                ),
                {
                    "monitoring_run_id": monitoring_run_id,
                    "business_date": business_date,
                    "latest_actual_date": latest_actual_date,
                    "status": status,
                    "official_total_count": official_total_count,
                    "matched_total_count": matched_total_count,
                    "waiting_for_actual_count": waiting_for_actual_count,
                    "missing_actual_count": missing_actual_count,
                },
            )

    def monitoring_run_id_for_pipeline(
        self,
        pipeline_run_id: str,
    ) -> str | None:
        return self.conn.execute(
            text(
                """
                SELECT monitoring_run_id
                FROM dbo.production_monitoring_runs
                WHERE pipeline_run_id=:pipeline_run_id
                """
            ),
            {"pipeline_run_id": pipeline_run_id},
        ).scalar()

    def insert_metric(self, row: dict) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.production_monitoring_metrics
                (
                    monitoring_run_id,
                    metric_scope,
                    horizon,
                    candidate_id,
                    department_id,
                    sample_count,
                    through_target_date,
                    mae,
                    rmse,
                    wape,
                    r2,
                    bias,
                    p90_abs_error,
                    max_abs_error,
                    within_2_rate,
                    underprediction_rate,
                    underprediction_mae,
                    capacity_event_tp,
                    capacity_event_fp,
                    capacity_event_fn,
                    capacity_event_tn,
                    capacity_event_precision,
                    capacity_event_recall,
                    capacity_event_accuracy,
                    created_at
                )
                VALUES
                (
                    :monitoring_run_id,
                    :metric_scope,
                    :horizon,
                    :candidate_id,
                    :department_id,
                    :sample_count,
                    :through_target_date,
                    :mae,
                    :rmse,
                    :wape,
                    :r2,
                    :bias,
                    :p90_abs_error,
                    :max_abs_error,
                    :within_2_rate,
                    :underprediction_rate,
                    :underprediction_mae,
                    :capacity_event_tp,
                    :capacity_event_fp,
                    :capacity_event_fn,
                    :capacity_event_tn,
                    :capacity_event_precision,
                    :capacity_event_recall,
                    :capacity_event_accuracy,
                    SYSUTCDATETIME()
                )
                """
            ),
            row,
        )

    def finish_monitoring_run_metric_count(
        self,
        *,
        monitoring_run_id: str,
        metric_row_count: int,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.production_monitoring_runs
                SET
                    metric_row_count=:metric_row_count,
                    completed_at=SYSUTCDATETIME()
                WHERE monitoring_run_id=:monitoring_run_id
                """
            ),
            {
                "monitoring_run_id": monitoring_run_id,
                "metric_row_count": metric_row_count,
            },
        )

    def latest_data_ready_pipeline(self) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    status,
                    completed_at
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).mappings().first()

        return None if row is None else dict(row)