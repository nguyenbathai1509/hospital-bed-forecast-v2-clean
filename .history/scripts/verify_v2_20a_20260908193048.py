from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text

from src.db.engine import create_sql_engine
from src.evaluation.service import (
    EXPECTED_TEST_ROWS_PER_CANDIDATE,
    EXPECTED_TEST_ROWS_PER_DEPARTMENT,
    MAE_ABS_TOLERANCE,
)


EXPECTED_RUN_ID = "TRN_20260907T105913Z_686E6A0C"
EXPECTED_TOTAL = 8 * EXPECTED_TEST_ROWS_PER_CANDIDATE


def main() -> None:
    engine = create_sql_engine()

    with engine.connect() as conn:
        migrations = [
            str(value)
            for value in conn.execute(
                text(
                    """
                    SELECT migration_id
                    FROM dbo.schema_migrations
                    ORDER BY migration_id
                    """
                )
            ).scalars().all()
        ]

        run = conn.execute(
            text(
                """
                SELECT
                    run_id,
                    business_date,
                    status,
                    data_version,
                    feature_version,
                    random_seed,
                    completed_candidate_count
                FROM dbo.training_runs
                WHERE run_id=:run_id
                """
            ),
            {"run_id": EXPECTED_RUN_ID},
        ).mappings().first()

        total = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.model_evaluation_predictions
                    WHERE run_id=:run_id
                    """
                ),
                {"run_id": EXPECTED_RUN_ID},
            ).scalar_one()
        )

        candidate_counts = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        candidate_id,
                        horizon,
                        model_family,
                        COUNT(*) AS row_count,
                        COUNT(DISTINCT department_id) AS department_count,
                        MIN(target_date) AS min_target_date,
                        MAX(target_date) AS max_target_date
                    FROM dbo.model_evaluation_predictions
                    WHERE run_id=:run_id
                    GROUP BY candidate_id, horizon, model_family
                    ORDER BY horizon, model_family
                    """
                ),
                {"run_id": EXPECTED_RUN_ID},
            ).mappings().all()
        ]

        department_counts = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        candidate_id,
                        department_id,
                        COUNT(*) AS row_count
                    FROM dbo.model_evaluation_predictions
                    WHERE run_id=:run_id
                    GROUP BY candidate_id, department_id
                    ORDER BY candidate_id, department_id
                    """
                ),
                {"run_id": EXPECTED_RUN_ID},
            ).mappings().all()
        ]

        metrics = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        ep.candidate_id,
                        ep.horizon,
                        ep.model_family,
                        COUNT(*) AS sample_count,
                        AVG(ep.absolute_error) AS replay_mae,
                        mc.mae AS registry_mae,
                        ABS(AVG(ep.absolute_error) - mc.mae) AS mae_delta,
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
                {"run_id": EXPECTED_RUN_ID},
            ).mappings().all()
        ]

        duplicate_keys = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT candidate_id, origin_date, department_id
                        FROM dbo.model_evaluation_predictions
                        WHERE run_id=:run_id
                        GROUP BY candidate_id, origin_date, department_id
                        HAVING COUNT(*) > 1
                    ) d
                    """
                ),
                {"run_id": EXPECTED_RUN_ID},
            ).scalar_one()
        )

    payload = {
        "run": None if run is None else dict(run),
        "migrations": migrations,
        "prediction_count": total,
        "candidate_count": len(candidate_counts),
        "candidate_counts": candidate_counts,
        "department_counts": department_counts,
        "metrics": metrics,
        "duplicate_keys": duplicate_keys,
        "mae_abs_tolerance": MAE_ABS_TOLERANCE,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    assert run is not None
    assert run["status"] == "COMPLETED"
    assert "009_model_evaluation_predictions.sql" in migrations
    assert total == EXPECTED_TOTAL
    assert len(candidate_counts) == 8
    assert duplicate_keys == 0

    for row in candidate_counts:
        assert int(row["row_count"]) == EXPECTED_TEST_ROWS_PER_CANDIDATE
        assert int(row["department_count"]) == 2
        assert row["min_target_date"] == date(2026, 5, 25)
        assert row["max_target_date"] == date(2026, 6, 30)

    assert len(department_counts) == 16
    for row in department_counts:
        assert int(row["row_count"]) == EXPECTED_TEST_ROWS_PER_DEPARTMENT

    assert len(metrics) == 8
    for row in metrics:
        assert int(row["sample_count"]) == EXPECTED_TEST_ROWS_PER_CANDIDATE
        assert float(row["mae_delta"]) <= MAE_ABS_TOLERANCE

    print("\nV2-20A VERIFY: PASS")


if __name__ == "__main__":
    main()