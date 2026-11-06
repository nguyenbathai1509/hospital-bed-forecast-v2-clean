from __future__ import annotations

import json

from sqlalchemy import text

from src.db.engine import create_sql_engine


EXPECTED_FAMILY = {
    1: "RF",
    3: "SVR",
}


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        origin_date = conn.execute(
            text(
                """
                SELECT TOP 1 business_date
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).scalar()

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

        drafts = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        fd.draft_id,
                        fd.origin_date,
                        fd.department_id,
                        fd.horizon,
                        fd.target_date,
                        fd.candidate_id,
                        mc.model_family,
                        fd.status,
                        fd.prediction_raw,
                        fd.prediction_rounded,
                        fd.planned_beds,
                        fd.predicted_utilization_pct,
                        fd.capacity_alert,
                        fd.capacity_excess_beds
                    FROM dbo.forecast_drafts fd
                    JOIN dbo.model_candidates mc
                        ON mc.candidate_id=fd.candidate_id
                    WHERE fd.origin_date=:origin_date
                    ORDER BY fd.horizon, fd.department_id, fd.created_at
                    """
                ),
                {"origin_date": origin_date},
            ).mappings().all()
        ]

        officials = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        ofc.official_id,
                        ofc.source_draft_id,
                        ofc.origin_date,
                        ofc.department_id,
                        ofc.horizon,
                        ofc.target_date,
                        ofc.candidate_id,
                        mc.model_family,
                        ofc.prediction_raw,
                        ofc.prediction_rounded,
                        ofc.planned_beds,
                        ofc.predicted_utilization_pct,
                        ofc.capacity_alert,
                        ofc.capacity_excess_beds,
                        ofc.confirmed_by,
                        ofc.issued_at
                    FROM dbo.official_forecasts ofc
                    JOIN dbo.model_candidates mc
                        ON mc.candidate_id=ofc.candidate_id
                    WHERE ofc.origin_date=:origin_date
                    ORDER BY ofc.horizon, ofc.department_id
                    """
                ),
                {"origin_date": origin_date},
            ).mappings().all()
        ]

        locks = [
            dict(row)
            for row in conn.execute(
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
                    WHERE dml.origin_date=:origin_date
                    ORDER BY dml.horizon
                    """
                ),
                {"origin_date": origin_date},
            ).mappings().all()
        ]

        open_draft_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.forecast_drafts
                    WHERE origin_date=:origin_date AND status='DRAFT'
                    """
                ),
                {"origin_date": origin_date},
            ).scalar_one()
        )

        official_duplicate_keys = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT
                            origin_date,
                            department_id,
                            horizon
                        FROM dbo.official_forecasts
                        WHERE origin_date=:origin_date
                        GROUP BY
                            origin_date,
                            department_id,
                            horizon
                        HAVING COUNT(*)>1
                    ) x
                    """
                ),
                {"origin_date": origin_date},
            ).scalar_one()
        )

    locks_by_horizon = {
        int(row["horizon"]): row
        for row in locks
    }

    official_keys = {
        (
            int(row["department_id"]),
            int(row["horizon"]),
        )
        for row in officials
    }

    expected_keys = {
        (343, 1),
        (344, 1),
        (343, 3),
        (344, 3),
    }

    official_lock_match = all(
        row["candidate_id"]
        == locks_by_horizon[
            int(row["horizon"])
        ]["model_candidate_id"]
        for row in officials
        if int(row["horizon"])
        in locks_by_horizon
    )

    value_contract = all(
        int(row["prediction_rounded"]) >= 0
        and int(row["planned_beds"]) > 0
        and int(row["capacity_excess_beds"])
        == max(
            0,
            int(row["prediction_rounded"])
            - int(row["planned_beds"]),
        )
        and bool(row["capacity_alert"])
        == (
            int(row["prediction_rounded"])
            > int(row["planned_beds"])
        )
        for row in officials
    )

    target_date_contract = all(
        (
            row["target_date"]
            - row["origin_date"]
        ).days
        == int(row["horizon"])
        for row in officials
    )

    report = {
        "origin_date": origin_date,
        "migrations": migrations,
        "draft_count": len(drafts),
        "open_draft_count": open_draft_count,
        "drafts": drafts,
        "official_count": len(officials),
        "official_duplicate_keys": official_duplicate_keys,
        "officials": officials,
        "daily_model_lock_count": len(locks),
        "daily_model_locks": locks,
        "official_lock_match": official_lock_match,
        "target_date_contract": target_date_contract,
        "value_contract": value_contract,
    }

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    ok = (
        "006_forecast_lifecycle.sql" in migrations
        and origin_date is not None
        and len(drafts) == 4
        and open_draft_count == 0
        and all(
            row["status"] == "CONFIRMED"
            for row in drafts
        )
        and len(officials) == 4
        and official_duplicate_keys == 0
        and official_keys == expected_keys
        and len(locks) == 2
        and locks_by_horizon.get(1, {}).get(
            "model_family"
        ) == EXPECTED_FAMILY[1]
        and locks_by_horizon.get(3, {}).get(
            "model_family"
        ) == EXPECTED_FAMILY[3]
        and official_lock_match
        and target_date_contract
        and value_contract
    )

    print(
        "\nV2-17 VERIFY: "
        + ("PASS" if ok else "FAIL")
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())