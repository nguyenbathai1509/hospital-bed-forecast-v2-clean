from __future__ import annotations

import json

from sqlalchemy import text

from src.db.engine import create_sql_engine


EXPECTED_BOOTSTRAP = {
    1: "RF",
    3: "SVR",
}


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        run = conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    status,
                    completed_at
                FROM dbo.training_runs
                WHERE status='COMPLETED'
                ORDER BY completed_at DESC
                """
            )
        ).mappings().first()

        if run is None:
            print(
                "No COMPLETED Training Run found"
            )
            print(
                "\nV2-15 VERIFY: FAIL"
            )
            return 1

        recommendations = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        mr.recommendation_id,
                        mr.run_id,
                        mr.horizon,
                        mr.best_candidate_id,
                        best.model_family AS best_family,
                        mr.champion_candidate_id,
                        champion.model_family AS champion_family,
                        mr.recommended_candidate_id,
                        recommended.model_family AS recommended_family,
                        mr.champion_source,
                        mr.action,
                        mr.improvement_pct,
                        mr.minimum_improvement_pct,
                        mr.guardrail_pass,
                        mr.reason_code,
                        mr.reason_json,
                        mr.guardrail_json,
                        mr.policy_json,
                        mr.created_at
                    FROM dbo.model_recommendations mr
                    JOIN dbo.model_candidates best
                        ON best.candidate_id = mr.best_candidate_id
                    JOIN dbo.model_candidates champion
                        ON champion.candidate_id = mr.champion_candidate_id
                    JOIN dbo.model_candidates recommended
                        ON recommended.candidate_id = mr.recommended_candidate_id
                    WHERE mr.run_id=:run_id
                    ORDER BY mr.horizon
                    """
                ),
                {
                    "run_id": run["run_id"],
                },
            ).mappings().all()
        ]

        ranking_rows = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        mcr.recommendation_id,
                        mcr.horizon,
                        mcr.rank_no,
                        mcr.candidate_id,
                        mc.model_family,
                        mcr.is_best_candidate,
                        mcr.mae
                    FROM dbo.model_candidate_rankings mcr
                    JOIN dbo.model_candidates mc
                        ON mc.candidate_id = mcr.candidate_id
                    JOIN dbo.model_recommendations mr
                        ON mr.recommendation_id = mcr.recommendation_id
                    WHERE mr.run_id=:run_id
                    ORDER BY mcr.horizon, mcr.rank_no
                    """
                ),
                {
                    "run_id": run["run_id"],
                },
            ).mappings().all()
        ]

        recommended_flags = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        candidate_id,
                        horizon,
                        model_family,
                        registry_status,
                        is_recommended
                    FROM dbo.model_candidates
                    WHERE is_recommended=1
                    ORDER BY horizon
                    """
                )
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

        migrations = [
            row["migration_id"]
            for row in conn.execute(
                text(
                    """
                    SELECT migration_id
                    FROM dbo.schema_migrations
                    ORDER BY migration_id
                    """
                )
            ).mappings().all()
        ]

    report = {
        "training_run": dict(run),
        "recommendation_count": len(
            recommendations
        ),
        "recommendations": recommendations,
        "ranking_row_count": len(
            ranking_rows
        ),
        "rankings": ranking_rows,
        "recommended_flag_count": len(
            recommended_flags
        ),
        "recommended_flags": recommended_flags,
        "active_production_count": (
            active_production_count
        ),
        "migrations": migrations,
    }

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    by_horizon = {
        int(row["horizon"]): row
        for row in recommendations
    }

    ranks_by_horizon = {
        horizon: [
            row
            for row in ranking_rows
            if int(
                row["horizon"]
            ) == horizon
        ]
        for horizon in (1, 3)
    }

    flags_by_horizon = {
        int(row["horizon"]): row
        for row in recommended_flags
    }

    h1 = by_horizon.get(1)
    h3 = by_horizon.get(3)

    ok = (
        "004_recommendation_engine.sql"
        in migrations
        and len(recommendations) == 2
        and len(ranking_rows) == 8
        and all(
            len(
                ranks_by_horizon[h]
            ) == 4
            for h in (1, 3)
        )
        and all(
            [
                int(row["rank_no"])
                for row
                in ranks_by_horizon[h]
            ]
            == [1, 2, 3, 4]
            for h in (1, 3)
        )
        and len(
            recommended_flags
        ) == 2
        and h1 is not None
        and h3 is not None
        and h1[
            "champion_source"
        ] == "BOOTSTRAP_REFERENCE"
        and h3[
            "champion_source"
        ] == "BOOTSTRAP_REFERENCE"
        and h1[
            "champion_family"
        ] == EXPECTED_BOOTSTRAP[1]
        and h3[
            "champion_family"
        ] == EXPECTED_BOOTSTRAP[3]
        and h1[
            "best_family"
        ] == "SVR"
        and h3[
            "best_family"
        ] == "SVR"
        and h1[
            "action"
        ] == "KEEP"
        and h3[
            "action"
        ] == "KEEP"
        and h1[
            "recommended_family"
        ] == "RF"
        and h3[
            "recommended_family"
        ] == "SVR"
        and flags_by_horizon.get(
            1,
            {},
        ).get(
            "model_family"
        ) == "RF"
        and flags_by_horizon.get(
            3,
            {},
        ).get(
            "model_family"
        ) == "SVR"
        and 0.0
        <= float(
            h1["improvement_pct"]
        )
        < 1.0
        and abs(
            float(
                h3["improvement_pct"]
            )
        ) <= 1e-12
    )

    print(
        "\nV2-15 VERIFY: "
        + ("PASS" if ok else "FAIL")
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())