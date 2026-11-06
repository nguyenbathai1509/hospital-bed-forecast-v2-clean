from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from src.db.engine import create_sql_engine
from src.predictors.integrity import verify_artifact_sha256
from src.training.config import EXPECTED_FAMILIES, EXPECTED_HORIZONS
from src.training.service import PROJECT_ROOT


def _resolve_artifact(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        run = conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id, business_date, status, data_version, feature_version,
                    row_count, department_count, random_seed, code_revision,
                    training_contract_version, completed_candidate_count,
                    started_at, completed_at
                FROM dbo.training_runs
                WHERE status='COMPLETED'
                ORDER BY completed_at DESC
                """
            )
        ).mappings().first()

        if run is None:
            print("No COMPLETED Training Run found")
            print("\nV2-14 VERIFY: FAIL")
            return 1

        candidates = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        candidate_id, horizon, model_family,
                        artifact_path, artifact_type, inference_type, artifact_sha256,
                        feature_version, data_version,
                        mae, rmse, wape, r2, bias,
                        p90_abs_error, max_abs_error, within_2_rate,
                        underprediction_rate, underprediction_mae,
                        best_params_json, model_metadata_json
                    FROM dbo.model_candidates
                    WHERE run_id=:run_id
                    ORDER BY horizon, model_family
                    """
                ),
                {"run_id": run["run_id"]},
            ).mappings().all()
        ]

        per_department = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT md.candidate_id, mc.horizon, mc.model_family,
                           md.department_id, md.sample_count, md.mae, md.wape,
                           md.bias, md.max_abs_error
                    FROM dbo.model_metrics_by_department md
                    JOIN dbo.model_candidates mc
                      ON mc.candidate_id=md.candidate_id
                    WHERE mc.run_id=:run_id
                    ORDER BY mc.horizon, mc.model_family, md.department_id
                    """
                ),
                {"run_id": run["run_id"]},
            ).mappings().all()
        ]

        active_production_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.production_models
                    WHERE slot_status='ACTIVE'
                    """
                )
            ).scalar_one()
        )

    artifact_errors = []

    for candidate in candidates:
        try:
            path = _resolve_artifact(
                candidate["artifact_path"]
            )

            verify_artifact_sha256(
                path,
                candidate["artifact_sha256"],
            )

        except Exception as exc:
            artifact_errors.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "error": str(exc),
                }
            )

    counts = {}

    for horizon in EXPECTED_HORIZONS:
        counts[str(horizon)] = {
            family: sum(
                1
                for c in candidates
                if (
                    int(c["horizon"]) == horizon
                    and c["model_family"] == family
                )
            )
            for family in EXPECTED_FAMILIES
        }

    svr_h1 = next(
        (
            c
            for c in candidates
            if (
                int(c["horizon"]) == 1
                and c["model_family"] == "SVR"
            )
        ),
        None,
    )

    svr_h3 = next(
        (
            c
            for c in candidates
            if (
                int(c["horizon"]) == 3
                and c["model_family"] == "SVR"
            )
        ),
        None,
    )

    report = {
        "training_run": dict(run),
        "candidate_count": len(candidates),
        "candidate_matrix": counts,
        "per_department_metric_rows": len(per_department),
        "active_production_count": active_production_count,
        "artifact_integrity_errors": artifact_errors,
        "svr_h1_mae": (
            None
            if svr_h1 is None
            else svr_h1["mae"]
        ),
        "svr_h3_mae": (
            None
            if svr_h3 is None
            else svr_h3["mae"]
        ),
        "candidates": candidates,
    }

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    matrix_ok = all(
        counts[str(h)][family] == 1
        for h in EXPECTED_HORIZONS
        for family in EXPECTED_FAMILIES
    )

    metric_ok = all(
        candidate["mae"] is not None
        and candidate["rmse"] is not None
        and candidate["wape"] is not None
        and candidate["bias"] is not None
        for candidate in candidates
    )

    svr_contract_ok = (
        svr_h1 is not None
        and svr_h3 is not None
        and abs(
            float(svr_h1["mae"]) - 2.2482
        ) <= 0.03
        and abs(
            float(svr_h3["mae"]) - 2.2094
        ) <= 0.03
    )

    ok = (
        run["status"] == "COMPLETED"
        and int(
            run["completed_candidate_count"] or 0
        ) == 8
        and int(
            run["row_count"] or 0
        ) == 704
        and int(
            run["department_count"] or 0
        ) == 2
        and len(candidates) == 8
        and matrix_ok
        and len(per_department) == 16
        and not artifact_errors
        and metric_ok
        and svr_contract_ok
    )

    print(
        "\nV2-14 VERIFY: "
        + ("PASS" if ok else "FAIL")
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())