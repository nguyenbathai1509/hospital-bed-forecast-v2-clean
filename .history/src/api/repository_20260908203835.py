from __future__ import annotations

from datetime import date
import json

from sqlalchemy import text
from sqlalchemy.engine import Connection


class ApiReadRepository:
    """Read-only SQL queries used by FastAPI presentation endpoints.

    Business mutations remain in the existing V2 services. This repository only
    exposes compact read models required by API status/navigation screens.
    """

    def __init__(self, conn: Connection):
        self.conn = conn

    def latest_data_status(self) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    source_mode,
                    data_version,
                    rows_extracted,
                    quality_error_count,
                    quality_warning_count,
                    quality_check_count,
                    completed_at
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).mappings().first()

        return None if row is None else dict(row)

    def latest_actual_date(self):
        return self.conn.execute(
            text(
                """
                SELECT MAX(business_date)
                FROM dbo.clean_bed_daily
                """
            )
        ).scalar()

    def active_department_count(self) -> int:
        return int(
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.departments
                    WHERE is_active=1
                    """
                )
            ).scalar_one()
        )

    def departments(self) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    department_id,
                    department_code,
                    department_name,
                    planned_beds,
                    is_active
                FROM dbo.departments
                WHERE is_active=1
                ORDER BY department_id
                """
            )
        ).mappings().all()

        return [dict(row) for row in rows]

    def pipeline_run_exists(self, run_id: str) -> bool:
        return (
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.pipeline_runs
                    WHERE run_id=:run_id
                    """
                ),
                {"run_id": run_id},
            ).scalar_one()
            > 0
        )

    def latest_pipeline_run_id(self) -> str | None:
        value = self.conn.execute(
            text(
                """
                SELECT TOP 1 run_id
                FROM dbo.pipeline_runs
                ORDER BY started_at DESC, run_id DESC
                """
            )
        ).scalar()

        return None if value is None else str(value)

    def pipeline_runs(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        where = ""
        params: dict[str, object] = {
            "limit": int(limit),
            "offset": int(offset),
        }

        if status is not None:
            where = "WHERE status=:status"
            params["status"] = status

        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    run_id,
                    business_date,
                    source_mode,
                    data_version,
                    status,
                    started_at,
                    completed_at,
                    rows_extracted,
                    quality_error_count,
                    quality_warning_count,
                    quality_check_count,
                    error_message
                FROM dbo.pipeline_runs
                {where}
                ORDER BY started_at DESC, run_id DESC
                OFFSET :offset ROWS
                FETCH NEXT :limit ROWS ONLY
                """
            ),
            params,
        ).mappings().all()

        return [dict(row) for row in rows]

    def data_quality_issues(
        self,
        *,
        pipeline_run_id: str,
        business_date: date | None,
        department_id: int | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        clauses = ["pipeline_run_id=:pipeline_run_id"]
        params: dict[str, object] = {
            "pipeline_run_id": pipeline_run_id,
            "limit": int(limit),
            "offset": int(offset),
        }

        if business_date is not None:
            clauses.append("business_date=:business_date")
            params["business_date"] = business_date

        if department_id is not None:
            clauses.append("department_id=:department_id")
            params["department_id"] = int(department_id)

        if severity is not None:
            clauses.append("severity=:severity")
            params["severity"] = severity

        where = " AND ".join(clauses)

        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    issue_id,
                    pipeline_run_id,
                    business_date,
                    department_id,
                    rule_id,
                    severity,
                    field_name,
                    expected_value,
                    actual_value,
                    difference_value,
                    message,
                    detected_at,
                    is_resolved
                FROM dbo.data_quality_issues
                WHERE {where}
                ORDER BY detected_at DESC, issue_id DESC
                OFFSET :offset ROWS
                FETCH NEXT :limit ROWS ONLY
                """
            ),
            params,
        ).mappings().all()

        return [dict(row) for row in rows]

    def department_exists(self, department_id: int) -> bool:
        return (
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.departments
                    WHERE department_id=:department_id
                    """
                ),
                {"department_id": int(department_id)},
            ).scalar_one()
            > 0
        )

    def history_rows(
        self,
        *,
        department_id: int,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        clauses = ["department_id=:department_id"]
        params: dict[str, object] = {
            "department_id": int(department_id),
            "limit": int(limit),
            "offset": int(offset),
        }

        if start_date is not None:
            clauses.append("business_date>=:start_date")
            params["start_date"] = start_date

        if end_date is not None:
            clauses.append("business_date<=:end_date")
            params["end_date"] = end_date

        where = " AND ".join(clauses)

        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    business_date,
                    department_id,
                    department_code,
                    department_name,
                    planned_beds,
                    occupied_start,
                    admissions,
                    transfer_in,
                    discharges,
                    transfer_out,
                    occupied_end,
                    occupied_beds,
                    (
                        admissions
                        + transfer_in
                        - discharges
                        - transfer_out
                    ) AS net_flow,
                    CAST(occupied_beds AS FLOAT)
                        / CAST(planned_beds AS FLOAT)
                        * 100.0 AS occupancy_rate_pct,
                    quality_flag,
                    source_revision_no
                FROM dbo.clean_bed_daily
                WHERE {where}
                ORDER BY business_date ASC
                OFFSET :offset ROWS
                FETCH NEXT :limit ROWS ONLY
                """
            ),
            params,
        ).mappings().all()

        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # V2-19 Part C1 - Training API read models
    # ------------------------------------------------------------------

    def training_job(self, job_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    job_id,
                    business_date,
                    source_pipeline_run_id,
                    status,
                    requested_by,
                    random_seed,
                    training_run_id,
                    created_at,
                    started_at,
                    completed_at,
                    error_message
                FROM dbo.api_training_jobs
                WHERE job_id=:job_id
                """
            ),
            {"job_id": job_id},
        ).mappings().first()
        return None if row is None else dict(row)

    def training_runs(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        where = ""
        params: dict[str, object] = {
            "limit": int(limit),
            "offset": int(offset),
        }

        if status is not None:
            where = "WHERE status=:status"
            params["status"] = status

        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    run_id,
                    business_date,
                    status,
                    triggered_by,
                    scope,
                    data_start,
                    data_end,
                    data_version,
                    feature_version,
                    row_count,
                    department_count,
                    random_seed,
                    training_contract_version,
                    completed_candidate_count,
                    started_at,
                    completed_at,
                    error_message
                FROM dbo.training_runs
                {where}
                ORDER BY started_at DESC, run_id DESC
                OFFSET :offset ROWS
                FETCH NEXT :limit ROWS ONLY
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def training_run(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    run_id,
                    business_date,
                    status,
                    triggered_by,
                    scope,
                    data_start,
                    data_end,
                    data_version,
                    feature_version,
                    row_count,
                    department_count,
                    random_seed,
                    training_contract_version,
                    completed_candidate_count,
                    started_at,
                    completed_at,
                    error_message
                FROM dbo.training_runs
                WHERE run_id=:run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()
        return None if row is None else dict(row)

    def candidates_for_training_run(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    registry_status,
                    is_recommended,
                    artifact_type,
                    inference_type,
                    feature_version,
                    data_version,
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
                    created_at
                FROM dbo.model_candidates
                WHERE run_id=:run_id
                ORDER BY horizon, model_family
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def department_metrics_for_training_run(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    md.candidate_id,
                    md.department_id,
                    md.sample_count,
                    md.mae,
                    md.rmse,
                    md.wape,
                    md.r2,
                    md.bias,
                    md.p90_abs_error,
                    md.max_abs_error,
                    md.within_2_rate,
                    md.underprediction_rate,
                    md.underprediction_mae
                FROM dbo.model_metrics_by_department md
                JOIN dbo.model_candidates mc
                    ON mc.candidate_id=md.candidate_id
                WHERE mc.run_id=:run_id
                ORDER BY mc.horizon, mc.model_family, md.department_id
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    @staticmethod
    def _json_load(value, default):
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)

    def recommendations_for_training_run(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    recommendation_id,
                    run_id,
                    horizon,
                    best_candidate_id,
                    champion_candidate_id,
                    recommended_candidate_id,
                    champion_source,
                    action,
                    improvement_pct,
                    minimum_improvement_pct,
                    guardrail_pass,
                    reason_code,
                    reason_json,
                    guardrail_json,
                    policy_json,
                    created_at
                FROM dbo.model_recommendations
                WHERE run_id=:run_id
                ORDER BY horizon
                """
            ),
            {"run_id": run_id},
        ).mappings().all()

        result = []
        for row in rows:
            item = dict(row)
            item["reasons"] = self._json_load(item.pop("reason_json"), [])
            item["guardrails"] = self._json_load(item.pop("guardrail_json"), [])
            item["policy"] = self._json_load(item.pop("policy_json"), {})
            result.append(item)
        return result

    def rankings_for_training_run(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    r.recommendation_id,
                    r.candidate_id,
                    r.horizon,
                    r.rank_no,
                    r.is_best_candidate,
                    r.mae,
                    r.rmse,
                    r.wape,
                    r.r2,
                    r.bias,
                    r.p90_abs_error,
                    r.max_abs_error,
                    r.within_2_rate,
                    r.underprediction_rate,
                    r.underprediction_mae
                FROM dbo.model_candidate_rankings r
                JOIN dbo.model_recommendations rec
                    ON rec.recommendation_id=r.recommendation_id
                WHERE rec.run_id=:run_id
                ORDER BY r.horizon, r.rank_no
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]



    # ------------------------------------------------------------------
    # V2-20B - read-only Training evaluation evidence
    # ------------------------------------------------------------------

    def training_evaluation_split(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    run_id,
                    data_start,
                    split_spec_json
                FROM dbo.training_runs
                WHERE run_id=:run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

        if row is None:
            return None

        item = dict(row)
        split = self._json_load(item.get("split_spec_json"), {})
        required = (
            "train_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        )
        if any(not split.get(key) for key in required):
            return None

        return {
            "train_start": item.get("data_start"),
            "train_end": split["train_end"],
            "validation_start": split["validation_start"],
            "validation_end": split["validation_end"],
            "test_start": split["test_start"],
            "test_end": split["test_end"],
        }

    def training_evaluation_rows(
        self,
        *,
        run_id: str,
        horizon: int,
        model_family: str,
        department_id: int | None,
    ) -> list[dict]:
        clauses = [
            "run_id=:run_id",
            "horizon=:horizon",
            "model_family=:model_family",
            "split_name='TEST'",
        ]
        params: dict[str, object] = {
            "run_id": run_id,
            "horizon": int(horizon),
            "model_family": model_family,
        }

        if department_id is not None:
            clauses.append("department_id=:department_id")
            params["department_id"] = int(department_id)

        where = " AND ".join(clauses)
        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    department_id,
                    origin_date,
                    target_date,
                    actual_occupied_beds,
                    prediction_raw,
                    residual,
                    absolute_error
                FROM dbo.model_evaluation_predictions
                WHERE {where}
                ORDER BY target_date, department_id
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]


    # ------------------------------------------------------------------
    # V2-19 Part C2 - Model Registry / Production read models
    # ------------------------------------------------------------------

    def model_candidates(
        self,
        *,
        run_id: str | None,
        horizon: int | None,
        model_family: str | None,
        registry_status: str | None,
        is_recommended: bool | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: dict[str, object] = {
            "limit": int(limit),
            "offset": int(offset),
        }

        if run_id is not None:
            clauses.append("run_id=:run_id")
            params["run_id"] = run_id

        if horizon is not None:
            clauses.append("horizon=:horizon")
            params["horizon"] = int(horizon)

        if model_family is not None:
            clauses.append("model_family=:model_family")
            params["model_family"] = model_family

        if registry_status is not None:
            clauses.append("registry_status=:registry_status")
            params["registry_status"] = registry_status

        if is_recommended is not None:
            clauses.append("is_recommended=:is_recommended")
            params["is_recommended"] = int(is_recommended)

        where = " AND ".join(clauses)

        rows = self.conn.execute(
            text(
                f"""
                SELECT
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    scope,
                    registry_status,
                    is_recommended,
                    artifact_type,
                    inference_type,
                    feature_version,
                    data_version,
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
                    created_at,
                    updated_at
                FROM dbo.model_candidates
                WHERE {where}
                ORDER BY run_id DESC, horizon, model_family
                OFFSET :offset ROWS
                FETCH NEXT :limit ROWS ONLY
                """
            ),
            params,
        ).mappings().all()

        return [dict(row) for row in rows]

    def latest_data_ready_business_date(self):
        return self.conn.execute(
            text(
                """
                SELECT TOP 1 business_date
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).scalar()

    def current_production_slots(self, horizon: int) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    pm.production_id,
                    pm.horizon,
                    pm.candidate_id,
                    mc.model_family,
                    pm.slot_status,
                    mc.registry_status,
                    mc.is_recommended,
                    mc.mae,
                    pm.effective_from_business_date,
                    pm.effective_to_business_date,
                    pm.promoted_by,
                    pm.promotion_reason,
                    pm.created_at
                FROM dbo.production_models pm
                JOIN dbo.model_candidates mc
                  ON mc.candidate_id=pm.candidate_id
                WHERE
                    pm.horizon=:horizon
                    AND pm.slot_status IN ('ACTIVE','SCHEDULED')
                ORDER BY
                    CASE pm.slot_status WHEN 'ACTIVE' THEN 1 ELSE 2 END,
                    pm.production_id DESC
                """
            ),
            {"horizon": int(horizon)},
        ).mappings().all()

        return [dict(row) for row in rows]

    def daily_model_lock(self, origin_date, horizon: int) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    dml.origin_date,
                    dml.horizon,
                    dml.model_candidate_id,
                    mc.model_family,
                    dml.trigger_department_id,
                    dml.locked_at
                FROM dbo.daily_model_locks dml
                JOIN dbo.model_candidates mc
                  ON mc.candidate_id=dml.model_candidate_id
                WHERE
                    dml.origin_date=:origin_date
                    AND dml.horizon=:horizon
                """
            ),
            {
                "origin_date": origin_date,
                "horizon": int(horizon),
            },
        ).mappings().first()

        return None if row is None else dict(row)

    def latest_recommendation_for_horizon(self, horizon: int) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    mr.recommendation_id,
                    mr.horizon,
                    mr.recommended_candidate_id,
                    mc.model_family AS recommended_family,
                    mr.action,
                    mr.guardrail_pass,
                    mr.created_at
                FROM dbo.model_recommendations mr
                JOIN dbo.model_candidates mc
                  ON mc.candidate_id=mr.recommended_candidate_id
                JOIN dbo.training_runs tr
                  ON tr.run_id=mr.run_id
                WHERE
                    mr.horizon=:horizon
                    AND tr.status='COMPLETED'
                ORDER BY tr.completed_at DESC, mr.created_at DESC
                """
            ),
            {"horizon": int(horizon)},
        ).mappings().first()

        return None if row is None else dict(row)

    def normal_production_change_exists(self, business_date) -> bool:
        if business_date is None:
            return False

        value = self.conn.execute(
            text(
                """
                SELECT TOP 1 1
                FROM dbo.production_changes
                WHERE
                    business_date=:business_date
                    AND change_kind='NORMAL_PROMOTION'
                    AND status='COMMITTED'
                """
            ),
            {"business_date": business_date},
        ).scalar()

        return value is not None


    # ------------------------------------------------------------------
    # V2-19 Part D - Forecast / Official / Monitoring read models
    # ------------------------------------------------------------------
    def forecast_drafts(self, *, origin_date=None, department_id=None, horizon=None, status=None, limit=100, offset=0) -> list[dict]:
        clauses = ["1=1"]
        params = {"limit": int(limit), "offset": int(offset)}
        if origin_date is not None:
            clauses.append("fd.origin_date=:origin_date"); params["origin_date"] = origin_date
        if department_id is not None:
            clauses.append("fd.department_id=:department_id"); params["department_id"] = int(department_id)
        if horizon is not None:
            clauses.append("fd.horizon=:horizon"); params["horizon"] = int(horizon)
        if status is not None:
            clauses.append("fd.status=:status"); params["status"] = status
        rows = self.conn.execute(text(f"""
            SELECT fd.draft_id, fd.origin_date, fd.department_id, fd.horizon, fd.target_date,
                   fd.candidate_id, mc.model_family, fd.source_mode, fd.status, fd.prediction_raw,
                   fd.prediction_rounded, fd.planned_beds, fd.predicted_utilization_pct,
                   fd.capacity_alert, fd.capacity_excess_beds, fd.feature_version, fd.data_version,
                   fd.created_by, fd.created_at, fd.confirmed_at
            FROM dbo.forecast_drafts fd
            JOIN dbo.model_candidates mc ON mc.candidate_id=fd.candidate_id
            WHERE {' AND '.join(clauses)}
            ORDER BY fd.origin_date DESC, fd.horizon, fd.department_id
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """), params).mappings().all()
        return [dict(row) for row in rows]

    def official_forecasts(self, *, origin_date=None, department_id=None, horizon=None, limit=100, offset=0) -> list[dict]:
        clauses = ["1=1"]
        params = {"limit": int(limit), "offset": int(offset)}
        if origin_date is not None:
            clauses.append("ofc.origin_date=:origin_date"); params["origin_date"] = origin_date
        if department_id is not None:
            clauses.append("ofc.department_id=:department_id"); params["department_id"] = int(department_id)
        if horizon is not None:
            clauses.append("ofc.horizon=:horizon"); params["horizon"] = int(horizon)
        rows = self.conn.execute(text(f"""
            SELECT ofc.official_id, ofc.source_draft_id, ofc.origin_date, ofc.department_id,
                   ofc.horizon, ofc.target_date, ofc.candidate_id, mc.model_family,
                   ofc.prediction_raw, ofc.prediction_rounded, ofc.planned_beds,
                   ofc.predicted_utilization_pct, ofc.capacity_alert, ofc.capacity_excess_beds,
                   ofc.feature_version, ofc.data_version, ofc.confirmed_by, ofc.issued_at
            FROM dbo.official_forecasts ofc
            JOIN dbo.model_candidates mc ON mc.candidate_id=ofc.candidate_id
            WHERE {' AND '.join(clauses)}
            ORDER BY ofc.origin_date DESC, ofc.horizon, ofc.department_id
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """), params).mappings().all()
        return [dict(row) for row in rows]

    def latest_monitoring_run(self) -> dict | None:
        row = self.conn.execute(text("""
            SELECT TOP 1 monitoring_run_id, pipeline_run_id, business_date, latest_actual_date, status,
                         official_total_count, matched_total_count, waiting_for_actual_count,
                         missing_actual_count, metric_row_count, started_at, completed_at
            FROM dbo.production_monitoring_runs
            ORDER BY completed_at DESC, started_at DESC
        """)).mappings().first()
        return None if row is None else dict(row)

    def monitoring_metrics(self, monitoring_run_id: str) -> list[dict]:
        rows = self.conn.execute(text("""
            SELECT metric_scope, horizon, candidate_id, department_id, sample_count, through_target_date,
                   mae, rmse, wape, r2, bias, p90_abs_error, max_abs_error, within_2_rate,
                   underprediction_rate, underprediction_mae, capacity_event_tp, capacity_event_fp,
                   capacity_event_fn, capacity_event_tn, capacity_event_precision, capacity_event_recall,
                   capacity_event_accuracy
            FROM dbo.production_monitoring_metrics
            WHERE monitoring_run_id=:monitoring_run_id
            ORDER BY horizon, metric_scope, department_id
        """), {"monitoring_run_id": monitoring_run_id}).mappings().all()
        return [dict(row) for row in rows]