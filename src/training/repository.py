from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.features.builder import (
    FEATURE_VALUE_COLUMNS,
)


class TrainingRepository:
    def __init__(
        self,
        conn: Connection,
    ):
        self.conn = conn

    def latest_data_ready_context(
        self,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    data_version,
                    source_mode,
                    completed_at
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY
                    completed_at DESC,
                    started_at DESC
                """
            )
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def completed_run_for_business_date(
        self,
        business_date: date,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1 *
                FROM dbo.training_runs
                WHERE
                    business_date=:business_date
                    AND status='COMPLETED'
                ORDER BY completed_at DESC
                """
            ),
            {
                "business_date": (
                    business_date
                )
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def create_training_run(
        self,
        *,
        run_id: str,
        business_date: date,
        triggered_by: str,
        data_start: date,
        data_end: date,
        data_version: str | None,
        feature_version: str,
        feature_hash: str,
        row_count: int,
        department_count: int,
        split_spec: dict,
        algorithm_set: dict,
        code_revision: str,
        random_seed: int,
        environment: dict,
        training_contract_version: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.training_runs
                (
                    run_id,
                    business_date,
                    status,
                    triggered_by,
                    scope,

                    data_start,
                    data_end,
                    data_version,

                    feature_version,
                    feature_hash,

                    row_count,
                    department_count,

                    split_spec_json,
                    algorithm_set_json,

                    started_at,

                    code_revision,
                    random_seed,
                    environment_json,

                    training_contract_version
                )
                VALUES
                (
                    :run_id,
                    :business_date,
                    'RUNNING',
                    :triggered_by,
                    'GLOBAL',

                    :data_start,
                    :data_end,
                    :data_version,

                    :feature_version,
                    :feature_hash,

                    :row_count,
                    :department_count,

                    :split_spec_json,
                    :algorithm_set_json,

                    SYSUTCDATETIME(),

                    :code_revision,
                    :random_seed,
                    :environment_json,

                    :training_contract_version
                )
                """
            ),
            {
                "run_id": run_id,
                "business_date": (
                    business_date
                ),
                "triggered_by": (
                    triggered_by
                ),
                "data_start": (
                    data_start
                ),
                "data_end": (
                    data_end
                ),
                "data_version": (
                    data_version
                ),
                "feature_version": (
                    feature_version
                ),
                "feature_hash": (
                    feature_hash
                ),
                "row_count": (
                    row_count
                ),
                "department_count": (
                    department_count
                ),
                "split_spec_json": (
                    json.dumps(
                        split_spec,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "algorithm_set_json": (
                    json.dumps(
                        algorithm_set,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "code_revision": (
                    code_revision
                ),
                "random_seed": (
                    random_seed
                ),
                "environment_json": (
                    json.dumps(
                        environment,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "training_contract_version": (
                    training_contract_version
                ),
            },
        )

    def finish_training_run(
        self,
        run_id: str,
        *,
        status: str,
        candidate_count: int,
        error_message: (
            str
            | None
        ) = None,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.training_runs
                SET
                    status=:status,
                    completed_at=SYSUTCDATETIME(),
                    completed_candidate_count=:candidate_count,
                    error_message=:error_message
                WHERE run_id=:run_id
                """
            ),
            {
                "run_id": (
                    run_id
                ),
                "status": (
                    status
                ),
                "candidate_count": (
                    candidate_count
                ),
                "error_message": (
                    error_message
                ),
            },
        )

    def fetch_tabular_dataset(
        self,
        horizon: int,
        feature_version: str,
    ) -> list[dict]:
        feature_select = (
            ",\n                    ".join(
                f"bf.{name} AS {name}"
                for name
                in FEATURE_VALUE_COLUMNS
            )
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
              ON
                    bf.origin_date
                    = ms.origin_date
                AND bf.department_id
                    = ms.department_id
                AND bf.feature_version
                    = ms.feature_version

            WHERE
                    ms.horizon=:horizon
                AND ms.feature_version=:feature_version

            ORDER BY
                ms.target_date,
                ms.department_id
        """

        rows = self.conn.execute(
            text(sql),
            {
                "horizon": (
                    horizon
                ),
                "feature_version": (
                    feature_version
                ),
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def fetch_feature_history(
        self,
        feature_version: str,
    ) -> list[dict]:
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

        select_cols = ", ".join(
            columns
        )

        rows = self.conn.execute(
            text(
                f"""
                SELECT {select_cols}
                FROM dbo.bed_features_daily
                WHERE
                    feature_version=:feature_version
                ORDER BY
                    department_id,
                    origin_date
                """
            ),
            {
                "feature_version": (
                    feature_version
                )
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def fetch_ml_samples(
        self,
        horizon: int,
        feature_version: str,
    ) -> list[dict]:
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
                WHERE
                    horizon=:horizon
                    AND
                    feature_version=:feature_version
                ORDER BY
                    target_date,
                    department_id
                """
            ),
            {
                "horizon": (
                    horizon
                ),
                "feature_version": (
                    feature_version
                ),
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def insert_candidate(
        self,
        *,
        candidate_id: str,
        run_id: str,
        horizon: int,
        model_family: str,
        artifact_path: str,
        artifact_type: str,
        inference_type: str,
        artifact_sha256: str,
        feature_version: str,
        data_version: str | None,
        feature_order: list[str],
        model_metadata: dict,
        best_params: dict,
        overall_metrics: dict,
        department_metrics: dict[
            int,
            dict,
        ],
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.model_candidates
                (
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,

                    scope,
                    registry_status,
                    is_recommended,

                    artifact_path,
                    artifact_type,
                    inference_type,
                    artifact_sha256,

                    feature_version,
                    data_version,

                    feature_order_json,
                    model_metadata_json,
                    best_params_json,

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
                )
                VALUES
                (
                    :candidate_id,
                    :run_id,
                    :horizon,
                    :model_family,

                    'GLOBAL',
                    'CANDIDATE',
                    0,

                    :artifact_path,
                    :artifact_type,
                    :inference_type,
                    :artifact_sha256,

                    :feature_version,
                    :data_version,

                    :feature_order_json,
                    :model_metadata_json,
                    :best_params_json,

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

                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                ),
                "run_id": (
                    run_id
                ),
                "horizon": (
                    horizon
                ),
                "model_family": (
                    model_family
                ),
                "artifact_path": (
                    artifact_path
                ),
                "artifact_type": (
                    artifact_type
                ),
                "inference_type": (
                    inference_type
                ),
                "artifact_sha256": (
                    artifact_sha256
                ),
                "feature_version": (
                    feature_version
                ),
                "data_version": (
                    data_version
                ),
                "feature_order_json": (
                    json.dumps(
                        feature_order,
                        ensure_ascii=False,
                    )
                ),
                "model_metadata_json": (
                    json.dumps(
                        model_metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "best_params_json": (
                    json.dumps(
                        best_params,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "mae": (
                    overall_metrics[
                        "mae"
                    ]
                ),
                "rmse": (
                    overall_metrics[
                        "rmse"
                    ]
                ),
                "wape": (
                    overall_metrics[
                        "wape"
                    ]
                ),
                "r2": (
                    overall_metrics[
                        "r2"
                    ]
                ),
                "bias": (
                    overall_metrics[
                        "bias"
                    ]
                ),
                "p90_abs_error": (
                    overall_metrics[
                        "p90_abs_error"
                    ]
                ),
                "max_abs_error": (
                    overall_metrics[
                        "max_abs_error"
                    ]
                ),
                "within_2_rate": (
                    overall_metrics[
                        "within_2_rate"
                    ]
                ),
                "underprediction_rate": (
                    overall_metrics[
                        "underprediction_rate"
                    ]
                ),
                "underprediction_mae": (
                    overall_metrics[
                        "underprediction_mae"
                    ]
                ),
            },
        )

        stmt = text(
            """
            INSERT INTO dbo.model_metrics_by_department
            (
                candidate_id,
                department_id,
                sample_count,

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
            )
            VALUES
            (
                :candidate_id,
                :department_id,
                :sample_count,

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

                SYSUTCDATETIME()
            )
            """
        )

        for (
            department_id,
            metrics,
        ) in sorted(
            department_metrics.items()
        ):
            params = dict(
                metrics
            )

            params.update(
                {
                    "candidate_id": (
                        candidate_id
                    ),
                    "department_id": (
                        department_id
                    ),
                }
            )

            self.conn.execute(
                stmt,
                params,
            )