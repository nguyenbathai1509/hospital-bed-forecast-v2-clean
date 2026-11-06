from __future__ import annotations

import json

from sqlalchemy import text

from src.config import settings
from src.db.engine import (
    create_sql_engine,
)


def _scalar(
    conn,
    sql: str,
    **params,
):
    return conn.execute(
        text(sql),
        params,
    ).scalar_one()


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        feature_count = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM dbo.bed_features_daily
                WHERE feature_version=:v
                """,
                v=settings.feature_version,
            )
        )

        feature_dupes = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM
                (
                    SELECT
                        origin_date,
                        department_id,
                        feature_version
                    FROM dbo.bed_features_daily
                    GROUP BY
                        origin_date,
                        department_id,
                        feature_version
                    HAVING COUNT(*) > 1
                ) q
                """,
            )
        )

        full_history_count = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM dbo.bed_features_daily
                WHERE
                    feature_version=:v
                    AND occupied_beds_lag_3
                        IS NOT NULL
                """,
                v=settings.feature_version,
            )
        )

        sample_count = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM dbo.ml_samples
                WHERE feature_version=:v
                """,
                v=settings.feature_version,
            )
        )

        sample_dupes = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM
                (
                    SELECT
                        origin_date,
                        department_id,
                        horizon,
                        feature_version
                    FROM dbo.ml_samples
                    GROUP BY
                        origin_date,
                        department_id,
                        horizon,
                        feature_version
                    HAVING COUNT(*) > 1
                ) q
                """,
            )
        )

        sample_counts = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        horizon,
                        department_id,
                        COUNT(*) AS row_count,
                        MIN(origin_date)
                            AS min_origin,
                        MAX(origin_date)
                            AS max_origin,
                        MIN(target_date)
                            AS min_target,
                        MAX(target_date)
                            AS max_target
                    FROM dbo.ml_samples
                    WHERE feature_version=:v
                    GROUP BY
                        horizon,
                        department_id
                    ORDER BY
                        horizon,
                        department_id
                    """
                ),
                {
                    "v": (
                        settings.feature_version
                    )
                },
            ).mappings().all()
        ]

        feature_ranges = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        department_id,
                        COUNT(*) AS row_count,
                        MIN(origin_date)
                            AS min_origin,
                        MAX(origin_date)
                            AS max_origin,
                        SUM(
                            CASE
                                WHEN
                                    occupied_beds_lag_3
                                    IS NULL
                                THEN 1
                                ELSE 0
                            END
                        ) AS lag3_null_rows
                    FROM dbo.bed_features_daily
                    WHERE feature_version=:v
                    GROUP BY department_id
                    ORDER BY department_id
                    """
                ),
                {
                    "v": (
                        settings.feature_version
                    )
                },
            ).mappings().all()
        ]

        examples = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        origin_date,
                        department_id,
                        occupied_beds,
                        occupied_beds_lag_1,
                        occupied_beds_lag_2,
                        occupied_beds_lag_3,
                        occupied_beds_mean_3,
                        occupied_beds_std_3,
                        net_flow,
                        net_flow_mean_3,
                        is_weekend,
                        dow_sin,
                        dow_cos
                    FROM dbo.bed_features_daily
                    WHERE
                        feature_version=:v
                        AND origin_date='2026-01-04'
                    ORDER BY department_id
                    """
                ),
                {
                    "v": (
                        settings.feature_version
                    )
                },
            ).mappings().all()
        ]

        latest_run = conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    source_mode,
                    status,
                    rows_extracted,
                    quality_error_count,
                    quality_warning_count,
                    quality_check_count,
                    data_version
                FROM dbo.pipeline_runs
                ORDER BY started_at DESC
                """
            )
        ).mappings().first()

        raw_revision_gt1 = int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM dbo.raw_bed_daily
                WHERE revision_no > 1
                """,
            )
        )

        distinct_sample_versions = int(
            _scalar(
                conn,
                """
                SELECT COUNT(
                    DISTINCT data_version
                )
                FROM dbo.ml_samples
                WHERE feature_version=:v
                """,
                v=settings.feature_version,
            )
        )

    report = {
        "feature_version": (
            settings.feature_version
        ),
        "feature_count": feature_count,
        "feature_duplicate_keys": (
            feature_dupes
        ),
        "feature_rows_with_full_lag3": (
            full_history_count
        ),
        "feature_ranges": (
            feature_ranges
        ),
        "feature_example_2026_01_04": (
            examples
        ),
        "ml_sample_count": (
            sample_count
        ),
        "ml_sample_duplicate_keys": (
            sample_dupes
        ),
        "ml_sample_counts": (
            sample_counts
        ),
        "ml_distinct_data_versions": (
            distinct_sample_versions
        ),
        "raw_revision_gt1": (
            raw_revision_gt1
        ),
        "latest_run": (
            dict(latest_run)
            if latest_run
            else None
        ),
    }

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    expected_samples = {
        (1, 343): 177,
        (1, 344): 177,
        (3, 343): 175,
        (3, 344): 175,
    }

    actual_samples = {
        (
            int(row["horizon"]),
            int(row["department_id"]),
        ): int(row["row_count"])
        for row in sample_counts
    }

    expected_sample_ranges = {
        (1, 343): (
            "2026-01-04",
            "2026-06-29",
            "2026-01-05",
            "2026-06-30",
        ),
        (1, 344): (
            "2026-01-04",
            "2026-06-29",
            "2026-01-05",
            "2026-06-30",
        ),
        (3, 343): (
            "2026-01-04",
            "2026-06-27",
            "2026-01-07",
            "2026-06-30",
        ),
        (3, 344): (
            "2026-01-04",
            "2026-06-27",
            "2026-01-07",
            "2026-06-30",
        ),
    }

    actual_sample_ranges = {
        (
            int(row["horizon"]),
            int(row["department_id"]),
        ): (
            str(row["min_origin"]),
            str(row["max_origin"]),
            str(row["min_target"]),
            str(row["max_target"]),
        )
        for row in sample_counts
    }

    expected_feature_ranges = {
        343: (
            181,
            "2026-01-01",
            "2026-06-30",
            3,
        ),
        344: (
            181,
            "2026-01-01",
            "2026-06-30",
            3,
        ),
    }

    actual_feature_ranges = {
        int(row["department_id"]): (
            int(row["row_count"]),
            str(row["min_origin"]),
            str(row["max_origin"]),
            int(row["lag3_null_rows"]),
        )
        for row in feature_ranges
    }

    checks = [
        feature_count == 362,
        feature_dupes == 0,
        full_history_count == 356,

        actual_feature_ranges
        == expected_feature_ranges,

        sample_count == 704,
        sample_dupes == 0,

        actual_samples
        == expected_samples,

        actual_sample_ranges
        == expected_sample_ranges,

        distinct_sample_versions == 1,

        raw_revision_gt1 == 0,

        latest_run is not None
        and latest_run["status"]
        == "DATA_READY",

        latest_run is not None
        and str(
            latest_run["business_date"]
        )
        == "2026-06-30",

        latest_run is not None
        and int(
            latest_run[
                "quality_error_count"
            ]
        )
        == 0,

        latest_run is not None
        and int(
            latest_run["quality_warning_count"]
        )
        == 0,

        latest_run is not None
        and int(
            latest_run[
                "quality_check_count"
            ]
        )
        == 2,
    ]

    ok = all(checks)

    print(
        "\nV2-12 VERIFY: "
        + (
            "PASS"
            if ok
            else "FAIL"
        )
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())