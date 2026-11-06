from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.features.builder import FEATURE_VALUE_COLUMNS


class EvaluationRepository:
    """SQL access for immutable row-level Training evaluation evidence."""

    def __init__(self, conn: Connection):
        self.conn = conn

    @staticmethod
    def _json_load(value, default):
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)

    def training_run(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    run_id,
                    business_date,
                    status,
                    data_start,
                    data_end,
                    data_version,
                    feature_version,
                    split_spec_json,
                    random_seed,
                    training_contract_version,
                    completed_candidate_count
                FROM dbo.training_runs
                WHERE run_id=:run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()
        if row is None:
            return None
        item = dict(row)
        item["split_spec"] = self._json_load(item.pop("split_spec_json"), {})
        return item

    def candidates(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    feature_version,
                    data_version,
                    best_params_json,
                    model_metadata_json,
                    mae
                FROM dbo.model_candidates
                WHERE run_id=:run_id
                ORDER BY horizon, model_family
                """
            ),
            {"run_id": run_id},
        ).mappings().all()

        result = []
        for row in rows:
            item = dict(row)
            item["best_params"] = self._json_load(item.pop("best_params_json"), {})
            item["model_metadata"] = self._json_load(
                item.pop("model_metadata_json"), {}
            )
            result.append(item)
        return result

    def fetch_tabular_dataset(self, horizon: int, feature_version: str) -> list[dict]:
        feature_select = ",\n                    ".join(
            f"bf.{name} AS {name}" for name in FEATURE_VALUE_COLUMNS
        )
        sql = f"""
            SELECT
                ms.origin_date,
                ms.department_id,
                ms.horizon,
                ms.target_date,
                ms.target_occupied_beds,
                ms.data_version,
                {feature_select}
            FROM dbo.ml_samples ms
            JOIN dbo.bed_features_daily bf
              ON bf.origin_date=ms.origin_date
             AND bf.department_id=ms.department_id
             AND bf.feature_version=ms.feature_version
            WHERE ms.horizon=:horizon
              AND ms.feature_version=:feature_version
            ORDER BY ms.target_date, ms.department_id
        """
        rows = self.conn.execute(
            text(sql),
            {"horizon": int(horizon), "feature_version": feature_version},
        ).mappings().all()
        return [dict(row) for row in rows]

    def fetch_feature_history(self, feature_version: str) -> list[dict]:
        columns = [
            "origin_date",
            "department_id",
            "planned_beds",
            "occupied_beds",
            "admissions",
            "discharges",
            "transfer_in",
            "transfer_out",
            "net_flow",
            "is_weekend",
            "dow_sin",
            "dow_cos",
        ]
        rows = self.conn.execute(
            text(
                f"""
                SELECT {', '.join(columns)}
                FROM dbo.bed_features_daily
                WHERE feature_version=:feature_version
                ORDER BY department_id, origin_date
                """
            ),
            {"feature_version": feature_version},
        ).mappings().all()
        return [dict(row) for row in rows]

    def fetch_ml_samples(self, horizon: int, feature_version: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    origin_date,
                    department_id,
                    horizon,
                    target_date,
                    target_occupied_beds,
                    data_version
                FROM dbo.ml_samples
                WHERE horizon=:horizon
                  AND feature_version=:feature_version
                ORDER BY target_date, department_id
                """
            ),
            {"horizon": int(horizon), "feature_version": feature_version},
        ).mappings().all()
        return [dict(row) for row in rows]

    def prediction_count(self, run_id: str) -> int:
        return int(
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.model_evaluation_predictions
                    WHERE run_id=:run_id
                    """
                ),
                {"run_id": run_id},
            ).scalar_one()
        )

    def prediction_counts_by_candidate(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    candidate_id,
                    horizon,
                    model_family,
                    COUNT(*) AS row_count,
                    MIN(target_date) AS min_target_date,
                    MAX(target_date) AS max_target_date,
                    COUNT(DISTINCT department_id) AS department_count
                FROM dbo.model_evaluation_predictions
                WHERE run_id=:run_id
                GROUP BY candidate_id, horizon, model_family
                ORDER BY horizon, model_family
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def replay_metrics(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    ep.candidate_id,
                    ep.horizon,
                    ep.model_family,
                    COUNT(*) AS sample_count,
                    AVG(ep.absolute_error) AS replay_mae,
                    mc.mae AS registry_mae,
                    AVG(ep.residual) AS replay_bias
                FROM dbo.model_evaluation_predictions ep
                JOIN dbo.model_candidates mc
                  ON mc.candidate_id=ep.candidate_id
                WHERE ep.run_id=:run_id
                GROUP BY
                    ep.candidate_id,
                    ep.horizon,
                    ep.model_family,
                    mc.mae
                ORDER BY ep.horizon, ep.model_family
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def insert_predictions(self, rows: Iterable[dict]) -> None:
        payload = list(rows)
        if not payload:
            return
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.model_evaluation_predictions
                (
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    split_name,
                    origin_date,
                    target_date,
                    department_id,
                    actual_occupied_beds,
                    prediction_raw,
                    residual,
                    absolute_error,
                    feature_version,
                    data_version,
                    replay_version,
                    created_at
                )
                VALUES
                (
                    :candidate_id,
                    :run_id,
                    :horizon,
                    :model_family,
                    'TEST',
                    :origin_date,
                    :target_date,
                    :department_id,
                    :actual_occupied_beds,
                    :prediction_raw,
                    :residual,
                    :absolute_error,
                    :feature_version,
                    :data_version,
                    :replay_version,
                    SYSUTCDATETIME()
                )
                """
            ),
            payload,
        )