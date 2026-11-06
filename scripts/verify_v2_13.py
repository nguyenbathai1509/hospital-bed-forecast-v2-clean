from __future__ import annotations

import json

from sqlalchemy import text

from src.db.engine import (
    create_sql_engine,
)


REQUIRED_TABLES = {
    "training_runs",
    "model_candidates",
    "model_metrics_by_department",
    "production_models",
}


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        tables = {
            row["name"]
            for row
            in conn.execute(
                text(
                    """
                    SELECT name
                    FROM sys.tables
                    WHERE schema_id
                        = SCHEMA_ID('dbo')
                    """
                )
            ).mappings().all()
        }

        migrations = [
            row["migration_id"]
            for row
            in conn.execute(
                text(
                    """
                    SELECT migration_id
                    FROM dbo.schema_migrations
                    ORDER BY migration_id
                    """
                )
            ).mappings().all()
        ]

        candidate_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.model_candidates
                    """
                )
            ).scalar_one()
        )

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

    missing = sorted(
        REQUIRED_TABLES
        - tables
    )

    report = {
        "required_tables": sorted(
            REQUIRED_TABLES
        ),
        "missing_tables": missing,
        "migrations": migrations,
        "candidate_count": (
            candidate_count
        ),
        "active_production_count": (
            active_production_count
        ),
        "expected_pre_training_state": {
            "candidate_count": 0,
            "active_production_count": 0,
        },
    }

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    ok = (
        not missing
        and "002_model_registry.sql"
        in migrations
        and candidate_count == 0
        and active_production_count == 0
    )

    print(
        "\nV2-13 VERIFY: "
        + (
            "PASS"
            if ok
            else "FAIL"
        )
    )

    return (
        0
        if ok
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )