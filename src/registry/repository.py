from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.registry.contracts import (
    ModelArtifactSpec,
)


def _json_load(
    value: str | None,
    default,
):
    if value is None or value == "":
        return default

    return json.loads(value)


class ModelRegistryRepository:
    def __init__(
        self,
        conn: Connection,
    ):
        self.conn = conn

    def get_candidate(
        self,
        candidate_id: str,
    ) -> ModelArtifactSpec | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    candidate_id,
                    run_id,
                    horizon,
                    model_family,
                    artifact_path,
                    artifact_type,
                    inference_type,
                    feature_version,
                    data_version,
                    artifact_sha256,
                    feature_order_json,
                    model_metadata_json
                FROM dbo.model_candidates
                WHERE candidate_id=:candidate_id
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

        spec = ModelArtifactSpec(
            candidate_id=row[
                "candidate_id"
            ],
            run_id=row["run_id"],
            horizon=int(
                row["horizon"]
            ),
            model_family=row[
                "model_family"
            ],
            artifact_path=row[
                "artifact_path"
            ],
            artifact_type=row[
                "artifact_type"
            ],
            inference_type=row[
                "inference_type"
            ],
            feature_version=row[
                "feature_version"
            ],
            data_version=row[
                "data_version"
            ],
            artifact_sha256=row[
                "artifact_sha256"
            ],
            feature_order=tuple(
                _json_load(
                    row[
                        "feature_order_json"
                    ],
                    [],
                )
            ),
            metadata=_json_load(
                row[
                    "model_metadata_json"
                ],
                {},
            ),
        )

        spec.validate()

        return spec

    def get_active_production(
        self,
        horizon: int,
    ) -> ModelArtifactSpec | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    mc.candidate_id
                FROM dbo.production_models pm

                JOIN dbo.model_candidates mc
                    ON mc.candidate_id
                    = pm.candidate_id

                WHERE
                    pm.horizon=:horizon
                    AND
                    pm.slot_status='ACTIVE'

                ORDER BY
                    pm.effective_from_business_date DESC,
                    pm.production_id DESC
                """
            ),
            {
                "horizon": horizon
            },
        ).mappings().first()

        if row is None:
            return None

        return self.get_candidate(
            row["candidate_id"]
        )

    def list_candidates(
        self,
        horizon: int | None = None,
    ) -> list[dict[str, Any]]:
        if horizon is None:
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
                        mae,
                        rmse,
                        wape,
                        r2,
                        bias,
                        created_at
                    FROM dbo.model_candidates
                    ORDER BY
                        created_at DESC,
                        horizon,
                        model_family
                    """
                )
            ).mappings().all()

        else:
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
                        mae,
                        rmse,
                        wape,
                        r2,
                        bias,
                        created_at
                    FROM dbo.model_candidates
                    WHERE horizon=:horizon
                    ORDER BY
                        created_at DESC,
                        model_family
                    """
                ),
                {
                    "horizon": horizon
                },
            ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]