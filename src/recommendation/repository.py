from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.recommendation.contracts import (
    CandidateMetrics,
    DepartmentMetrics,
    RecommendationDecision,
)


def _json_load(
    value: str | None,
    default,
):
    if value is None or value == "":
        return default

    return json.loads(value)


class RecommendationRepository:
    def __init__(
        self,
        conn: Connection,
    ):
        self.conn = conn

    def latest_completed_training_run(
        self,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    status,
                    data_version,
                    feature_version,
                    split_spec_json,
                    completed_at
                FROM dbo.training_runs
                WHERE status='COMPLETED'
                ORDER BY completed_at DESC
                """
            )
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def get_training_run(
        self,
        run_id: str,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    run_id,
                    business_date,
                    status,
                    data_version,
                    feature_version,
                    split_spec_json,
                    completed_at
                FROM dbo.training_runs
                WHERE run_id=:run_id
                """
            ),
            {
                "run_id": run_id
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def list_candidates_for_run_horizon(
        self,
        run_id: str,
        horizon: int,
    ) -> list[CandidateMetrics]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    mc.candidate_id,
                    mc.run_id,
                    mc.horizon,
                    mc.model_family,
                    mc.mae,
                    mc.rmse,
                    mc.wape,
                    mc.r2,
                    mc.bias,
                    mc.p90_abs_error,
                    mc.max_abs_error,
                    mc.within_2_rate,
                    mc.underprediction_rate,
                    mc.underprediction_mae,
                    tr.split_spec_json
                FROM dbo.model_candidates mc

                JOIN dbo.training_runs tr
                    ON tr.run_id = mc.run_id

                WHERE
                    mc.run_id=:run_id
                    AND mc.horizon=:horizon
                    AND mc.registry_status <> 'FAILED'

                ORDER BY mc.model_family
                """
            ),
            {
                "run_id": run_id,
                "horizon": horizon,
            },
        ).mappings().all()

        return [
            self._candidate_from_row(
                row
            )
            for row in rows
        ]

    def get_candidate_metrics(
        self,
        candidate_id: str,
    ) -> CandidateMetrics | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    mc.candidate_id,
                    mc.run_id,
                    mc.horizon,
                    mc.model_family,
                    mc.mae,
                    mc.rmse,
                    mc.wape,
                    mc.r2,
                    mc.bias,
                    mc.p90_abs_error,
                    mc.max_abs_error,
                    mc.within_2_rate,
                    mc.underprediction_rate,
                    mc.underprediction_mae,
                    tr.split_spec_json
                FROM dbo.model_candidates mc

                JOIN dbo.training_runs tr
                    ON tr.run_id = mc.run_id

                WHERE
                    mc.candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                )
            },
        ).mappings().first()

        if row is None:
            return None

        return self._candidate_from_row(
            row
        )

    def _candidate_from_row(
        self,
        row,
    ) -> CandidateMetrics:
        required = (
            "mae",
            "rmse",
            "wape",
            "bias",
            "p90_abs_error",
            "max_abs_error",
            "within_2_rate",
            "underprediction_rate",
            "underprediction_mae",
        )

        missing = [
            name
            for name in required
            if row[name] is None
        ]

        if missing:
            raise ValueError(
                f"Candidate "
                f"{row['candidate_id']} "
                f"has missing metrics: "
                f"{missing}"
            )

        return CandidateMetrics(
            candidate_id=(
                row["candidate_id"]
            ),
            run_id=row["run_id"],
            horizon=int(
                row["horizon"]
            ),
            model_family=(
                row["model_family"]
            ),
            mae=float(
                row["mae"]
            ),
            rmse=float(
                row["rmse"]
            ),
            wape=float(
                row["wape"]
            ),
            r2=(
                None
                if row["r2"] is None
                else float(
                    row["r2"]
                )
            ),
            bias=float(
                row["bias"]
            ),
            p90_abs_error=float(
                row["p90_abs_error"]
            ),
            max_abs_error=float(
                row["max_abs_error"]
            ),
            within_2_rate=float(
                row["within_2_rate"]
            ),
            underprediction_rate=float(
                row["underprediction_rate"]
            ),
            underprediction_mae=float(
                row["underprediction_mae"]
            ),
            split_spec=_json_load(
                row["split_spec_json"],
                {},
            ),
        )

    def metrics_by_department(
        self,
        candidate_ids: list[str],
    ) -> dict[
        str,
        dict[
            int,
            DepartmentMetrics,
        ],
    ]:
        if not candidate_ids:
            return {}

        placeholders = ", ".join(
            f":candidate_{index}"
            for index
            in range(
                len(candidate_ids)
            )
        )

        params = {
            f"candidate_{index}": (
                candidate_id
            )
            for index, candidate_id
            in enumerate(
                candidate_ids
            )
        }

        rows = self.conn.execute(
            text(
                f"""
                SELECT
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
                    underprediction_mae
                FROM dbo.model_metrics_by_department
                WHERE candidate_id IN (
                    {placeholders}
                )
                ORDER BY
                    candidate_id,
                    department_id
                """
            ),
            params,
        ).mappings().all()

        result: dict[
            str,
            dict[
                int,
                DepartmentMetrics,
            ],
        ] = {}

        for row in rows:
            candidate_id = (
                row["candidate_id"]
            )

            department_id = int(
                row["department_id"]
            )

            result.setdefault(
                candidate_id,
                {},
            )[department_id] = (
                DepartmentMetrics(
                    candidate_id=(
                        candidate_id
                    ),
                    department_id=(
                        department_id
                    ),
                    sample_count=int(
                        row["sample_count"]
                    ),
                    mae=float(
                        row["mae"]
                    ),
                    rmse=float(
                        row["rmse"]
                    ),
                    wape=float(
                        row["wape"]
                    ),
                    r2=(
                        None
                        if row["r2"]
                        is None
                        else float(
                            row["r2"]
                        )
                    ),
                    bias=float(
                        row["bias"]
                    ),
                    p90_abs_error=float(
                        row[
                            "p90_abs_error"
                        ]
                    ),
                    max_abs_error=float(
                        row[
                            "max_abs_error"
                        ]
                    ),
                    within_2_rate=float(
                        row[
                            "within_2_rate"
                        ]
                    ),
                    underprediction_rate=float(
                        row[
                            "underprediction_rate"
                        ]
                    ),
                    underprediction_mae=float(
                        row[
                            "underprediction_mae"
                        ]
                    ),
                )
            )

        return result

    def active_production_candidate_id(
        self,
        horizon: int,
        *,
        for_update: bool = False,
    ) -> str | None:
        lock_hint = "WITH (UPDLOCK, HOLDLOCK)" if for_update else ""
        return self.conn.execute(
            text(
                f"""
                SELECT TOP 1
                    candidate_id
                FROM dbo.production_models {lock_hint}
                WHERE
                    horizon=:horizon
                    AND slot_status='ACTIVE'
                ORDER BY
                    effective_from_business_date DESC,
                    production_id DESC
                """
            ),
            {
                "horizon": horizon
            },
        ).scalar()

    def bootstrap_candidate(
        self,
        run_id: str,
        horizon: int,
        model_family: str,
    ) -> CandidateMetrics | None:
        row = self.conn.execute(
            text(
                """
                SELECT candidate_id
                FROM dbo.model_candidates
                WHERE
                    run_id=:run_id
                    AND horizon=:horizon
                    AND model_family=:model_family
                """
            ),
            {
                "run_id": run_id,
                "horizon": horizon,
                "model_family": (
                    model_family
                ),
            },
        ).mappings().first()

        if row is None:
            return None

        return self.get_candidate_metrics(
            row["candidate_id"]
        )

    def get_existing_recommendation(
        self,
        run_id: str,
        horizon: int,
    ) -> dict | None:
        row = self.conn.execute(
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
                WHERE
                    run_id=:run_id
                    AND horizon=:horizon
                """
            ),
            {
                "run_id": run_id,
                "horizon": horizon,
            },
        ).mappings().first()

        if row is None:
            return None

        result = dict(row)

        result["reasons"] = (
            _json_load(
                result.pop(
                    "reason_json"
                ),
                [],
            )
        )

        result["guardrails"] = (
            _json_load(
                result.pop(
                    "guardrail_json"
                ),
                [],
            )
        )

        result["policy"] = (
            _json_load(
                result.pop(
                    "policy_json"
                ),
                {},
            )
        )

        return result

    def save_recommendation(
        self,
        *,
        recommendation_id: str,
        run_id: str,
        decision: RecommendationDecision,
        ranked_candidates: list[
            CandidateMetrics
        ],
        policy: dict,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.model_recommendations
                (
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
                )
                VALUES
                (
                    :recommendation_id,
                    :run_id,
                    :horizon,

                    :best_candidate_id,
                    :champion_candidate_id,
                    :recommended_candidate_id,

                    :champion_source,
                    :action,

                    :improvement_pct,
                    :minimum_improvement_pct,
                    :guardrail_pass,

                    :reason_code,
                    :reason_json,
                    :guardrail_json,
                    :policy_json,

                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "recommendation_id": (
                    recommendation_id
                ),
                "run_id": run_id,
                "horizon": (
                    decision.horizon
                ),
                "best_candidate_id": (
                    decision.best_candidate_id
                ),
                "champion_candidate_id": (
                    decision.champion_candidate_id
                ),
                "recommended_candidate_id": (
                    decision.recommended_candidate_id
                ),
                "champion_source": (
                    decision.champion_source
                ),
                "action": (
                    decision.action
                ),
                "improvement_pct": (
                    decision.improvement_pct
                ),
                "minimum_improvement_pct": (
                    decision.minimum_improvement_pct
                ),
                "guardrail_pass": int(
                    decision.guardrail_pass
                ),
                "reason_code": (
                    decision.reason_code
                ),
                "reason_json": (
                    json.dumps(
                        list(
                            decision.reasons
                        ),
                        ensure_ascii=False,
                    )
                ),
                "guardrail_json": (
                    json.dumps(
                        [
                            check.as_dict()
                            for check
                            in decision.guardrails
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
                "policy_json": (
                    json.dumps(
                        policy,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            },
        )

        rank_stmt = text(
            """
            INSERT INTO dbo.model_candidate_rankings
            (
                recommendation_id,
                candidate_id,
                horizon,
                rank_no,
                is_best_candidate,

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
                :recommendation_id,
                :candidate_id,
                :horizon,
                :rank_no,
                :is_best_candidate,

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
            rank_no,
            candidate,
        ) in enumerate(
            ranked_candidates,
            start=1,
        ):
            self.conn.execute(
                rank_stmt,
                {
                    "recommendation_id": (
                        recommendation_id
                    ),
                    "candidate_id": (
                        candidate.candidate_id
                    ),
                    "horizon": (
                        candidate.horizon
                    ),
                    "rank_no": rank_no,
                    "is_best_candidate": int(
                        rank_no == 1
                    ),
                    "mae": candidate.mae,
                    "rmse": candidate.rmse,
                    "wape": candidate.wape,
                    "r2": candidate.r2,
                    "bias": candidate.bias,
                    "p90_abs_error": (
                        candidate.p90_abs_error
                    ),
                    "max_abs_error": (
                        candidate.max_abs_error
                    ),
                    "within_2_rate": (
                        candidate.within_2_rate
                    ),
                    "underprediction_rate": (
                        candidate.underprediction_rate
                    ),
                    "underprediction_mae": (
                        candidate.underprediction_mae
                    ),
                },
            )

        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    is_recommended=0,

                    registry_status=(
                        CASE
                            WHEN
                                registry_status='RECOMMENDED'
                            THEN
                                'CANDIDATE'
                            ELSE
                                registry_status
                        END
                    ),

                    updated_at=SYSUTCDATETIME()

                WHERE horizon=:horizon
                """
            ),
            {
                "horizon": (
                    decision.horizon
                )
            },
        )

        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    is_recommended=1,

                    registry_status=(
                        CASE
                            WHEN
                                registry_status='CANDIDATE'
                            THEN
                                'RECOMMENDED'
                            ELSE
                                registry_status
                        END
                    ),

                    updated_at=SYSUTCDATETIME()

                WHERE
                    candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    decision.recommended_candidate_id
                )
            },
        )
