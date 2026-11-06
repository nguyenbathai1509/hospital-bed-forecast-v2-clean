from __future__ import annotations

import json

from sqlalchemy import text

from src.db.engine import (
    create_sql_engine,
)


def main() -> int:
    engine = (
        create_sql_engine()
    )

    with engine.connect() as conn:
        latest_pipeline = (
            conn.execute(
                text(
                    """
                    SELECT TOP 1
                        run_id,
                        business_date,
                        status,
                        completed_at
                    FROM dbo.pipeline_runs
                    WHERE status='DATA_READY'
                    ORDER BY
                        completed_at DESC,
                        started_at DESC
                    """
                )
            ).mappings().first()
        )

        if latest_pipeline is None:
            raise RuntimeError(
                "No DATA_READY pipeline run exists"
            )

        pipeline_run_id = (
            latest_pipeline[
                "run_id"
            ]
        )

        migrations = [
            row[
                "migration_id"
            ]
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

        latest_actual_date = (
            conn.execute(
                text(
                    """
                    SELECT MAX(business_date)
                    FROM dbo.clean_bed_daily
                    """
                )
            ).scalar()
        )

        expected = (
            conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*)
                            AS official_total_count,

                        SUM(
                            CASE
                                WHEN cb.occupied_beds IS NOT NULL
                                THEN 1
                                ELSE 0
                            END
                        )
                            AS actual_available_count,

                        SUM(
                            CASE
                                WHEN
                                    cb.occupied_beds IS NULL
                                    AND (
                                        dept_latest.latest_actual_date IS NULL
                                        OR ofc.target_date
                                           > dept_latest.latest_actual_date
                                    )
                                THEN 1
                                ELSE 0
                            END
                        )
                            AS waiting_for_actual_count,

                        SUM(
                            CASE
                                WHEN
                                    cb.occupied_beds IS NULL
                                    AND dept_latest.latest_actual_date IS NOT NULL
                                    AND ofc.target_date
                                        <= dept_latest.latest_actual_date
                                THEN 1
                                ELSE 0
                            END
                        )
                            AS missing_actual_count

                    FROM dbo.official_forecasts ofc

                    OUTER APPLY (
                        SELECT
                            MAX(c2.business_date)
                                AS latest_actual_date
                        FROM dbo.clean_bed_daily c2
                        WHERE
                            c2.department_id
                            = ofc.department_id
                    ) dept_latest

                    LEFT JOIN dbo.clean_bed_daily cb
                        ON
                            cb.business_date
                            = ofc.target_date
                            AND cb.department_id
                            = ofc.department_id
                    """
                )
            ).mappings().one()
        )

        match_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.official_actual_matches
                    """
                )
            ).scalar_one()
        )

        match_without_official = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.official_actual_matches m

                    LEFT JOIN dbo.official_forecasts ofc
                        ON
                            ofc.official_id
                            = m.official_id

                    WHERE
                        ofc.official_id IS NULL
                    """
                )
            ).scalar_one()
        )

        match_contract_violations = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.official_actual_matches
                    WHERE
                        ABS(
                            error_raw
                            - (
                                actual_occupied_beds
                                - prediction_raw
                            )
                        ) > 0.000000001

                        OR ABS(
                            abs_error_raw
                            - ABS(
                                actual_occupied_beds
                                - prediction_raw
                            )
                        ) > 0.000000001

                        OR error_rounded
                            <> (
                                actual_occupied_beds
                                - prediction_rounded
                            )

                        OR abs_error_rounded
                            <> ABS(
                                actual_occupied_beds
                                - prediction_rounded
                            )

                        OR underpredicted
                            <> CASE
                                WHEN
                                    prediction_raw
                                    < actual_occupied_beds
                                THEN 1
                                ELSE 0
                            END

                        OR overpredicted
                            <> CASE
                                WHEN
                                    prediction_raw
                                    > actual_occupied_beds
                                THEN 1
                                ELSE 0
                            END

                        OR exact_rounded
                            <> CASE
                                WHEN
                                    prediction_rounded
                                    = actual_occupied_beds
                                THEN 1
                                ELSE 0
                            END

                        OR actual_capacity_exceeded
                            <> CASE
                                WHEN
                                    actual_occupied_beds
                                    > planned_beds
                                THEN 1
                                ELSE 0
                            END

                        OR capacity_alert_correct
                            <> CASE
                                WHEN
                                    capacity_alert
                                    = CASE
                                        WHEN
                                            actual_occupied_beds
                                            > planned_beds
                                        THEN 1
                                        ELSE 0
                                    END
                                THEN 1
                                ELSE 0
                            END
                    """
                )
            ).scalar_one()
        )

        monitoring_run = (
            conn.execute(
                text(
                    """
                    SELECT TOP 1 *
                    FROM dbo.production_monitoring_runs
                    WHERE
                        pipeline_run_id=:pipeline_run_id
                    """
                ),
                {
                    "pipeline_run_id": (
                        pipeline_run_id
                    )
                },
            ).mappings().first()
        )

        metric_rows = []

        if monitoring_run is not None:
            metric_rows = [
                dict(
                    row
                )
                for row
                in conn.execute(
                    text(
                        """
                        SELECT
                            pmm.metric_scope,
                            pmm.horizon,
                            pmm.candidate_id,
                            mc.model_family,
                            pmm.department_id,
                            pmm.sample_count,
                            pmm.through_target_date,
                            pmm.mae,
                            pmm.rmse,
                            pmm.wape,
                            pmm.r2,
                            pmm.bias,
                            pmm.p90_abs_error,
                            pmm.max_abs_error,
                            pmm.within_2_rate,
                            pmm.underprediction_rate,
                            pmm.underprediction_mae,
                            pmm.capacity_event_tp,
                            pmm.capacity_event_fp,
                            pmm.capacity_event_fn,
                            pmm.capacity_event_tn,
                            pmm.capacity_event_precision,
                            pmm.capacity_event_recall,
                            pmm.capacity_event_accuracy

                        FROM dbo.production_monitoring_metrics pmm

                        JOIN dbo.model_candidates mc
                            ON
                                mc.candidate_id
                                = pmm.candidate_id

                        WHERE
                            pmm.monitoring_run_id
                            = :monitoring_run_id

                        ORDER BY
                            pmm.metric_scope,
                            pmm.horizon,
                            pmm.department_id
                        """
                    ),
                    {
                        "monitoring_run_id": (
                            monitoring_run[
                                "monitoring_run_id"
                            ]
                        )
                    },
                ).mappings().all()
            ]

        expected_metric_rows = int(
            conn.execute(
                text(
                    """
                    SELECT
                        COALESCE(
                            (
                                SELECT COUNT(*)
                                FROM (
                                    SELECT
                                        horizon,
                                        candidate_id
                                    FROM dbo.official_actual_matches
                                    GROUP BY
                                        horizon,
                                        candidate_id
                                ) h
                            ),
                            0
                        )
                        +
                        COALESCE(
                            (
                                SELECT COUNT(*)
                                FROM (
                                    SELECT
                                        horizon,
                                        candidate_id,
                                        department_id
                                    FROM dbo.official_actual_matches
                                    GROUP BY
                                        horizon,
                                        candidate_id,
                                        department_id
                                ) d
                            ),
                            0
                        )
                    """
                )
            ).scalar_one()
        )

    expected_official_total = int(
        expected[
            "official_total_count"
        ]
        or 0
    )

    expected_actual_available = int(
        expected[
            "actual_available_count"
        ]
        or 0
    )

    expected_waiting = int(
        expected[
            "waiting_for_actual_count"
        ]
        or 0
    )

    expected_missing = int(
        expected[
            "missing_actual_count"
        ]
        or 0
    )

    report = {
        "latest_pipeline": dict(
            latest_pipeline
        ),
        "latest_actual_date": (
            latest_actual_date
        ),
        "migrations": (
            migrations
        ),
        "expected_from_official_vs_clean": {
            "official_total_count": (
                expected_official_total
            ),
            "actual_available_count": (
                expected_actual_available
            ),
            "waiting_for_actual_count": (
                expected_waiting
            ),
            "missing_actual_count": (
                expected_missing
            ),
        },
        "actual_match_count": (
            match_count
        ),
        "match_without_official": (
            match_without_official
        ),
        "match_contract_violations": (
            match_contract_violations
        ),
        "monitoring_run": (
            None
            if monitoring_run is None
            else dict(
                monitoring_run
            )
        ),
        "expected_metric_row_count": (
            expected_metric_rows
        ),
        "metric_row_count": len(
            metric_rows
        ),
        "metrics": (
            metric_rows
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

    monitoring_ok = (
        monitoring_run is not None

        and int(
            monitoring_run[
                "official_total_count"
            ]
        )
        == expected_official_total

        and int(
            monitoring_run[
                "matched_total_count"
            ]
        )
        == expected_actual_available

        and int(
            monitoring_run[
                "waiting_for_actual_count"
            ]
        )
        == expected_waiting

        and int(
            monitoring_run[
                "missing_actual_count"
            ]
        )
        == expected_missing

        and int(
            monitoring_run[
                "metric_row_count"
            ]
        )
        == expected_metric_rows
    )

    ok = (
        "007_actual_matching_monitoring.sql"
        in migrations

        and
        match_count
        == expected_actual_available

        and
        match_without_official
        == 0

        and
        match_contract_violations
        == 0

        and
        len(
            metric_rows
        )
        == expected_metric_rows

        and monitoring_ok
    )

    print(
        "\nV2-18 VERIFY: "
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