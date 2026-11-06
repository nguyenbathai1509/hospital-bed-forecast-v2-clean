from __future__ import annotations

from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.quality.rules import QualityIssue


class CoreRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def create_pipeline_run(
        self,
        run_id: str,
        source_mode: str,
        source_ref: str,
        data_version: str | None,
        business_date=None,
        status: str = "RUNNING",
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.pipeline_runs
                    (
                        run_id,
                        business_date,
                        source_mode,
                        source_ref,
                        data_version,
                        status,
                        started_at
                    )
                VALUES
                    (
                        :run_id,
                        :business_date,
                        :source_mode,
                        :source_ref,
                        :data_version,
                        :status,
                        SYSUTCDATETIME()
                    )
                """
            ),
            {
                "run_id": run_id,
                "business_date": business_date,
                "source_mode": source_mode,
                "source_ref": source_ref,
                "data_version": data_version,
                "status": status,
            },
        )

    def finish_pipeline_run(
        self,
        run_id: str,
        status: str,
        rows_extracted: int,
        counts: dict[str, int],
        error_message: str | None = None,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.pipeline_runs
                SET
                    status=:status,
                    completed_at=SYSUTCDATETIME(),
                    rows_extracted=:rows_extracted,
                    quality_error_count=:error_count,
                    quality_warning_count=:warning_count,
                    quality_check_count=:check_count,
                    error_message=:error_message
                WHERE run_id=:run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "rows_extracted": rows_extracted,
                "error_count": counts.get("ERROR", 0),
                "warning_count": counts.get("WARNING", 0),
                "check_count": counts.get("CHECK", 0),
                "error_message": error_message,
            },
        )

    def upsert_departments(
        self,
        rows: Iterable[dict],
    ) -> None:
        by_dep: dict[int, dict] = {}

        for row in rows:
            by_dep[int(row["department_id"])] = row

        stmt = text(
            """
            UPDATE dbo.departments
            SET
                department_code=:department_code,
                department_name=:department_name,
                planned_beds=:planned_beds,
                is_active=1,
                updated_at=SYSUTCDATETIME()
            WHERE department_id=:department_id;

            IF @@ROWCOUNT = 0
            INSERT INTO dbo.departments
                (
                    department_id,
                    department_code,
                    department_name,
                    planned_beds,
                    is_active
                )
            VALUES
                (
                    :department_id,
                    :department_code,
                    :department_name,
                    :planned_beds,
                    1
                );
            """
        )

        for department_id, row in sorted(by_dep.items()):
            self.conn.execute(
                stmt,
                {
                    "department_id": department_id,
                    "department_code": str(
                        row["department_code"]
                    ),
                    "department_name": str(
                        row["department_name"]
                    ),
                    "planned_beds": int(
                        row["planned_beds"]
                    ),
                },
            )

    def upsert_raw(
        self,
        rows: Iterable[dict],
        run_id: str,
    ) -> dict[str, int]:
        stats = {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
        }

        lookup = text(
            """
            SELECT
                source_hash,
                revision_no
            FROM dbo.raw_bed_daily
                WITH (UPDLOCK, HOLDLOCK)
            WHERE
                business_date=:business_date
                AND department_id=:department_id
            """
        )

        insert = text(
            """
            INSERT INTO dbo.raw_bed_daily
            (
                business_date,
                source_weekday,
                source_month,
                department_id,
                department_code,
                department_name,
                planned_beds,
                occupied_start,
                admissions,
                transfer_in,
                discharges,
                transfer_out,
                occupied_end,
                occupied_beds,
                balance_status,
                occupancy_rate,
                source_file,
                source_row_num,
                source_hash,
                revision_no,
                ingested_at,
                pipeline_run_id
            )
            VALUES
            (
                :business_date,
                :source_weekday,
                :source_month,
                :department_id,
                :department_code,
                :department_name,
                :planned_beds,
                :occupied_start,
                :admissions,
                :transfer_in,
                :discharges,
                :transfer_out,
                :occupied_end,
                :occupied_beds,
                :balance_status,
                :occupancy_rate,
                :source_file,
                :source_row_num,
                :source_hash,
                1,
                SYSUTCDATETIME(),
                :pipeline_run_id
            )
            """
        )

        update = text(
            """
            UPDATE dbo.raw_bed_daily
            SET
                source_weekday=:source_weekday,
                source_month=:source_month,
                department_code=:department_code,
                department_name=:department_name,
                planned_beds=:planned_beds,
                occupied_start=:occupied_start,
                admissions=:admissions,
                transfer_in=:transfer_in,
                discharges=:discharges,
                transfer_out=:transfer_out,
                occupied_end=:occupied_end,
                occupied_beds=:occupied_beds,
                balance_status=:balance_status,
                occupancy_rate=:occupancy_rate,
                source_file=:source_file,
                source_row_num=:source_row_num,
                source_hash=:source_hash,
                revision_no=revision_no + 1,
                ingested_at=SYSUTCDATETIME(),
                pipeline_run_id=:pipeline_run_id
            WHERE
                business_date=:business_date
                AND department_id=:department_id
            """
        )

        for row in rows:
            params = dict(row)
            params["pipeline_run_id"] = run_id

            existing = self.conn.execute(
                lookup,
                {
                    "business_date": row["business_date"],
                    "department_id": row["department_id"],
                },
            ).mappings().first()

            if existing is None:
                self.conn.execute(
                    insert,
                    params,
                )
                stats["inserted"] += 1

            elif existing["source_hash"] == row["source_hash"]:
                stats["unchanged"] += 1

            else:
                self.conn.execute(
                    update,
                    params,
                )
                stats["updated"] += 1

        return stats

    def replace_issues_for_run(
        self,
        run_id: str,
        issues: Iterable[QualityIssue],
    ) -> None:
        self.conn.execute(
            text(
                """
                DELETE
                FROM dbo.data_quality_issues
                WHERE pipeline_run_id=:run_id
                """
            ),
            {
                "run_id": run_id,
            },
        )

        stmt = text(
            """
            INSERT INTO dbo.data_quality_issues
            (
                pipeline_run_id,
                business_date,
                department_id,
                rule_id,
                severity,
                field_name,
                expected_value,
                actual_value,
                difference_value,
                message,
                detected_at
            )
            VALUES
            (
                :pipeline_run_id,
                :business_date,
                :department_id,
                :rule_id,
                :severity,
                :field_name,
                :expected_value,
                :actual_value,
                :difference_value,
                :message,
                SYSUTCDATETIME()
            )
            """
        )

        for issue in issues:
            self.conn.execute(
                stmt,
                {
                    "pipeline_run_id": run_id,
                    "business_date": issue.business_date,
                    "department_id": issue.department_id,
                    "rule_id": issue.rule_id,
                    "severity": issue.severity,
                    "field_name": issue.field_name,
                    "expected_value": issue.expected_value,
                    "actual_value": issue.actual_value,
                    "difference_value": issue.difference_value,
                    "message": issue.message,
                },
            )

    def upsert_clean(
        self,
        rows: Iterable[dict],
        run_id: str,
        issue_by_key: dict[
            tuple,
            list[QualityIssue],
        ],
    ) -> None:
        stmt = text(
            """
            UPDATE dbo.clean_bed_daily
            SET
                department_code=:department_code,
                department_name=:department_name,
                planned_beds=:planned_beds,
                occupied_start=:occupied_start,
                admissions=:admissions,
                transfer_in=:transfer_in,
                discharges=:discharges,
                transfer_out=:transfer_out,
                occupied_end=:occupied_end,
                occupied_beds=:occupied_beds,
                balance_status=:balance_status,
                expected_occupied_end=:expected_occupied_end,
                balance_error=:balance_error,
                quality_flag=:quality_flag,
                occupied_consistency_error=:occupied_consistency_error,
                source_revision_no=:source_revision_no,
                pipeline_run_id=:pipeline_run_id,
                built_at=SYSUTCDATETIME()
            WHERE
                business_date=:business_date
                AND department_id=:department_id;

            IF @@ROWCOUNT = 0
            INSERT INTO dbo.clean_bed_daily
            (
                business_date,
                department_id,
                department_code,
                department_name,
                planned_beds,
                occupied_start,
                admissions,
                transfer_in,
                discharges,
                transfer_out,
                occupied_end,
                occupied_beds,
                balance_status,
                expected_occupied_end,
                balance_error,
                quality_flag,
                occupied_consistency_error,
                source_revision_no,
                pipeline_run_id,
                built_at
            )
            VALUES
            (
                :business_date,
                :department_id,
                :department_code,
                :department_name,
                :planned_beds,
                :occupied_start,
                :admissions,
                :transfer_in,
                :discharges,
                :transfer_out,
                :occupied_end,
                :occupied_beds,
                :balance_status,
                :expected_occupied_end,
                :balance_error,
                :quality_flag,
                :occupied_consistency_error,
                :source_revision_no,
                :pipeline_run_id,
                SYSUTCDATETIME()
            );
            """
        )

        revision_stmt = text(
            """
            SELECT revision_no
            FROM dbo.raw_bed_daily
            WHERE
                business_date=:business_date
                AND department_id=:department_id
            """
        )

        severity_rank = {
            "PASS": 0,
            "WARNING": 1,
            "CHECK": 2,
            "ERROR": 3,
        }

        for row in rows:
            expected_occupied_end = (
                row["occupied_start"]
                + row["admissions"]
                + row["transfer_in"]
                - row["discharges"]
                - row["transfer_out"]
            )

            balance_error = (
                row["occupied_end"]
                - expected_occupied_end
            )

            occupied_consistency_error = (
                row["occupied_end"]
                - row["occupied_beds"]
            )

            key = (
                row["business_date"],
                row["department_id"],
            )

            row_issues = issue_by_key.get(
                key,
                [],
            )

            quality_flag = "PASS"

            if row_issues:
                quality_flag = max(
                    (
                        issue.severity
                        for issue in row_issues
                    ),
                    key=lambda severity: (
                        severity_rank[severity]
                    ),
                )

            source_revision_no = self.conn.execute(
                revision_stmt,
                {
                    "business_date": row["business_date"],
                    "department_id": row["department_id"],
                },
            ).scalar_one()

            params = {
                "business_date": row["business_date"],
                "department_id": row["department_id"],
                "department_code": row["department_code"],
                "department_name": row["department_name"],
                "planned_beds": row["planned_beds"],
                "occupied_start": row["occupied_start"],
                "admissions": row["admissions"],
                "transfer_in": row["transfer_in"],
                "discharges": row["discharges"],
                "transfer_out": row["transfer_out"],
                "occupied_end": row["occupied_end"],
                "occupied_beds": row["occupied_beds"],
                "balance_status": row["balance_status"],
                "expected_occupied_end": expected_occupied_end,
                "balance_error": balance_error,
                "quality_flag": quality_flag,
                "occupied_consistency_error": (
                    occupied_consistency_error
                ),
                "source_revision_no": source_revision_no,
                "pipeline_run_id": run_id,
            }

            self.conn.execute(
                stmt,
                params,
            )

    def fetch_raw_rows(
        self,
    ) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    business_date,
                    source_weekday,
                    source_month,
                    department_id,
                    department_code,
                    department_name,
                    planned_beds,
                    occupied_start,
                    admissions,
                    transfer_in,
                    discharges,
                    transfer_out,
                    occupied_end,
                    occupied_beds,
                    balance_status,
                    occupancy_rate,
                    source_file,
                    source_row_num,
                    source_hash,
                    revision_no AS source_revision_no
                FROM dbo.raw_bed_daily
                ORDER BY
                    department_id,
                    business_date
                """
            )
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def fetch_clean_rows(
        self,
    ) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    business_date,
                    department_id,
                    department_code,
                    department_name,
                    planned_beds,
                    occupied_start,
                    admissions,
                    transfer_in,
                    discharges,
                    transfer_out,
                    occupied_end,
                    occupied_beds,
                    balance_status,
                    expected_occupied_end,
                    balance_error,
                    quality_flag,
                    occupied_consistency_error,
                    source_revision_no
                FROM dbo.clean_bed_daily
                ORDER BY
                    department_id,
                    business_date
                """
            )
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def replace_features(
        self,
        feature_rows: Iterable[dict],
        feature_version: str,
    ) -> int:
        self.conn.execute(
            text(
                """
                DELETE
                FROM dbo.bed_features_daily
                WHERE feature_version=:feature_version
                """
            ),
            {
                "feature_version": feature_version,
            },
        )

        stmt = text(
            """
            INSERT INTO dbo.bed_features_daily
            (
                origin_date,
                department_id,
                feature_version,
                planned_beds,
                occupied_beds,
                admissions,
                discharges,
                transfer_in,
                transfer_out,
                net_flow,
                occupied_beds_lag_1,
                occupied_beds_lag_2,
                occupied_beds_lag_3,
                occupied_beds_mean_3,
                occupied_beds_std_3,
                admissions_lag_1,
                admissions_lag_2,
                admissions_lag_3,
                admissions_mean_3,
                discharges_lag_1,
                discharges_lag_2,
                discharges_lag_3,
                discharges_mean_3,
                net_flow_lag_1,
                net_flow_lag_2,
                net_flow_lag_3,
                net_flow_mean_3,
                is_weekend,
                dow_sin,
                dow_cos,
                source_revision_no,
                built_at
            )
            VALUES
            (
                :origin_date,
                :department_id,
                :feature_version,
                :planned_beds,
                :occupied_beds,
                :admissions,
                :discharges,
                :transfer_in,
                :transfer_out,
                :net_flow,
                :occupied_beds_lag_1,
                :occupied_beds_lag_2,
                :occupied_beds_lag_3,
                :occupied_beds_mean_3,
                :occupied_beds_std_3,
                :admissions_lag_1,
                :admissions_lag_2,
                :admissions_lag_3,
                :admissions_mean_3,
                :discharges_lag_1,
                :discharges_lag_2,
                :discharges_lag_3,
                :discharges_mean_3,
                :net_flow_lag_1,
                :net_flow_lag_2,
                :net_flow_lag_3,
                :net_flow_mean_3,
                :is_weekend,
                :dow_sin,
                :dow_cos,
                :source_revision_no,
                SYSUTCDATETIME()
            )
            """
        )

        count = 0

        for row in feature_rows:
            self.conn.execute(
                stmt,
                dict(row),
            )
            count += 1

        return count

    def replace_ml_samples(
        self,
        sample_rows: Iterable[dict],
        feature_version: str,
    ) -> dict[int, int]:
        self.conn.execute(
            text(
                """
                DELETE
                FROM dbo.ml_samples
                WHERE feature_version=:feature_version
                """
            ),
            {
                "feature_version": feature_version,
            },
        )

        stmt = text(
            """
            INSERT INTO dbo.ml_samples
            (
                origin_date,
                department_id,
                horizon,
                target_date,
                target_occupied_beds,
                feature_version,
                data_version,
                matured_at
            )
            VALUES
            (
                :origin_date,
                :department_id,
                :horizon,
                :target_date,
                :target_occupied_beds,
                :feature_version,
                :data_version,
                SYSUTCDATETIME()
            )
            """
        )

        counts: dict[int, int] = {
            1: 0,
            3: 0,
        }

        for row in sample_rows:
            self.conn.execute(
                stmt,
                dict(row),
            )

            horizon = int(
                row["horizon"]
            )

            counts[horizon] = (
                counts.get(
                    horizon,
                    0,
                )
                + 1
            )

        return counts

    def feature_count(
        self,
        feature_version: str,
    ) -> int:
        return int(
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.bed_features_daily
                    WHERE feature_version=:feature_version
                    """
                ),
                {
                    "feature_version": feature_version,
                },
            ).scalar_one()
        )

    def ml_sample_counts(
        self,
        feature_version: str,
    ) -> dict[int, int]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    horizon,
                    COUNT(*) AS n
                FROM dbo.ml_samples
                WHERE feature_version=:feature_version
                GROUP BY horizon
                """
            ),
            {
                "feature_version": feature_version,
            },
        ).mappings().all()

        result = {
            1: 0,
            3: 0,
        }

        for row in rows:
            result[
                int(row["horizon"])
            ] = int(row["n"])

        return result