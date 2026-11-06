from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.features.builder import FEATURE_VALUE_COLUMNS


class ForecastRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def latest_data_ready_context(self) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    business_date,
                    data_version,
                    completed_at
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).mappings().first()

        return None if row is None else dict(row)

    def active_department_ids(self) -> list[int]:
        rows = self.conn.execute(
            text(
                """
                SELECT department_id
                FROM dbo.departments
                WHERE is_active=1
                ORDER BY department_id
                """
            )
        ).scalars().all()

        return [
            int(value)
            for value in rows
        ]

    def department_planned_beds(
        self,
        department_id: int,
    ) -> int:
        value = self.conn.execute(
            text(
                """
                SELECT planned_beds
                FROM dbo.departments
                WHERE department_id=:department_id
                """
            ),
            {
                "department_id": (
                    department_id
                )
            },
        ).scalar()

        if value is None:
            raise RuntimeError(
                f"Unknown department_id={department_id}"
            )

        return int(value)

    def feature_row(
        self,
        *,
        origin_date: date,
        department_id: int,
        feature_version: str,
    ) -> dict | None:
        select_values = ",\n                    ".join(
            FEATURE_VALUE_COLUMNS
        )

        row = self.conn.execute(
            text(
                f"""
                SELECT
                    origin_date,
                    feature_version,
                    {select_values}
                FROM dbo.bed_features_daily
                WHERE
                    origin_date=:origin_date
                    AND department_id=:department_id
                    AND feature_version=:feature_version
                """
            ),
            {
                "origin_date": origin_date,
                "department_id": department_id,
                "feature_version": feature_version,
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def sequence_rows(
        self,
        *,
        origin_date: date,
        department_id: int,
        feature_version: str,
    ) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT TOP 3
                    origin_date,
                    department_id,
                    planned_beds,
                    occupied_beds,
                    admissions,
                    discharges,
                    transfer_in,
                    transfer_out,
                    net_flow,
                    is_weekend,
                    dow_sin,
                    dow_cos
                FROM dbo.bed_features_daily
                WHERE
                    department_id=:department_id
                    AND feature_version=:feature_version
                    AND origin_date<=:origin_date
                ORDER BY origin_date DESC
                """
            ),
            {
                "origin_date": origin_date,
                "department_id": department_id,
                "feature_version": feature_version,
            },
        ).mappings().all()

        result = [
            dict(row)
            for row in reversed(rows)
        ]

        if (
            len(result) == 3
            and result[-1]["origin_date"]
            != origin_date
        ):
            return []

        return result

    def daily_lock_candidate_id(
        self,
        *,
        origin_date: date,
        horizon: int,
        for_update: bool = False,
    ) -> str | None:
        hint = (
            "WITH (UPDLOCK, HOLDLOCK)"
            if for_update
            else ""
        )

        return self.conn.execute(
            text(
                f"""
                SELECT model_candidate_id
                FROM dbo.daily_model_locks {hint}
                WHERE
                    origin_date=:origin_date
                    AND horizon=:horizon
                """
            ),
            {
                "origin_date": origin_date,
                "horizon": horizon,
            },
        ).scalar()

    def active_production_candidate_id(
        self,
        horizon: int,
    ) -> str | None:
        return self.conn.execute(
            text(
                """
                SELECT TOP 1 candidate_id
                FROM dbo.production_models
                WHERE
                    horizon=:horizon
                    AND slot_status='ACTIVE'
                ORDER BY production_id DESC
                """
            ),
            {
                "horizon": horizon
            },
        ).scalar()

    def latest_recommended_candidate_id(
        self,
        horizon: int,
    ) -> str | None:
        return self.conn.execute(
            text(
                """
                SELECT TOP 1
                    mr.recommended_candidate_id
                FROM dbo.model_recommendations mr
                JOIN dbo.training_runs tr
                    ON tr.run_id=mr.run_id
                WHERE mr.horizon=:horizon
                ORDER BY
                    tr.completed_at DESC,
                    mr.created_at DESC
                """
            ),
            {
                "horizon": horizon
            },
        ).scalar()

    def open_draft(
        self,
        *,
        origin_date: date,
        department_id: int,
        horizon: int,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1 *
                FROM dbo.forecast_drafts
                WHERE
                    origin_date=:origin_date
                    AND department_id=:department_id
                    AND horizon=:horizon
                    AND status='DRAFT'
                ORDER BY created_at DESC
                """
            ),
            {
                "origin_date": origin_date,
                "department_id": department_id,
                "horizon": horizon,
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def official_for_key(
        self,
        *,
        origin_date: date,
        department_id: int,
        horizon: int,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1 *
                FROM dbo.official_forecasts
                WHERE
                    origin_date=:origin_date
                    AND department_id=:department_id
                    AND horizon=:horizon
                """
            ),
            {
                "origin_date": origin_date,
                "department_id": department_id,
                "horizon": horizon,
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def void_open_draft(
        self,
        draft_id: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.forecast_drafts
                SET status='VOID'
                WHERE
                    draft_id=:draft_id
                    AND status='DRAFT'
                """
            ),
            {
                "draft_id": draft_id
            },
        )

    def insert_draft(
        self,
        row: dict,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.forecast_drafts
                (
                    draft_id,
                    origin_date,
                    department_id,
                    horizon,
                    target_date,
                    candidate_id,
                    source_mode,
                    status,
                    prediction_raw,
                    prediction_rounded,
                    planned_beds,
                    predicted_utilization_pct,
                    capacity_alert,
                    capacity_excess_beds,
                    feature_version,
                    data_version,
                    created_by,
                    created_at
                )
                VALUES
                (
                    :draft_id,
                    :origin_date,
                    :department_id,
                    :horizon,
                    :target_date,
                    :candidate_id,
                    'PRODUCTION',
                    'DRAFT',
                    :prediction_raw,
                    :prediction_rounded,
                    :planned_beds,
                    :predicted_utilization_pct,
                    :capacity_alert,
                    :capacity_excess_beds,
                    :feature_version,
                    :data_version,
                    :created_by,
                    SYSUTCDATETIME()
                )
                """
            ),
            row,
        )

    def list_open_drafts(
        self,
        *,
        origin_date: date,
    ) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    fd.*,
                    mc.model_family
                FROM dbo.forecast_drafts fd
                JOIN dbo.model_candidates mc
                    ON mc.candidate_id=fd.candidate_id
                WHERE
                    fd.origin_date=:origin_date
                    AND fd.status='DRAFT'
                ORDER BY
                    fd.horizon,
                    fd.department_id
                """
            ),
            {
                "origin_date": origin_date
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    def draft_for_update(
        self,
        draft_id: str,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT *
                FROM dbo.forecast_drafts
                    WITH (UPDLOCK, HOLDLOCK)
                WHERE draft_id=:draft_id
                """
            ),
            {
                "draft_id": draft_id
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def official_by_source_draft(
        self,
        draft_id: str,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT *
                FROM dbo.official_forecasts
                WHERE source_draft_id=:draft_id
                """
            ),
            {
                "draft_id": draft_id
            },
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def insert_daily_lock(
        self,
        *,
        origin_date: date,
        horizon: int,
        candidate_id: str,
        trigger_department_id: int,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.daily_model_locks
                (
                    origin_date,
                    horizon,
                    model_candidate_id,
                    locked_at,
                    trigger_department_id
                )
                VALUES
                (
                    :origin_date,
                    :horizon,
                    :candidate_id,
                    SYSUTCDATETIME(),
                    :trigger_department_id
                )
                """
            ),
            {
                "origin_date": origin_date,
                "horizon": horizon,
                "candidate_id": candidate_id,
                "trigger_department_id": (
                    trigger_department_id
                ),
            },
        )

    def insert_official(
        self,
        *,
        official_id: str,
        draft: dict,
        confirmed_by: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.official_forecasts
                (
                    official_id,
                    source_draft_id,
                    origin_date,
                    department_id,
                    horizon,
                    target_date,
                    candidate_id,
                    prediction_raw,
                    prediction_rounded,
                    planned_beds,
                    predicted_utilization_pct,
                    capacity_alert,
                    capacity_excess_beds,
                    feature_version,
                    data_version,
                    confirmed_by,
                    issued_at
                )
                VALUES
                (
                    :official_id,
                    :source_draft_id,
                    :origin_date,
                    :department_id,
                    :horizon,
                    :target_date,
                    :candidate_id,
                    :prediction_raw,
                    :prediction_rounded,
                    :planned_beds,
                    :predicted_utilization_pct,
                    :capacity_alert,
                    :capacity_excess_beds,
                    :feature_version,
                    :data_version,
                    :confirmed_by,
                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "official_id": official_id,
                "source_draft_id": (
                    draft["draft_id"]
                ),
                "origin_date": (
                    draft["origin_date"]
                ),
                "department_id": (
                    draft["department_id"]
                ),
                "horizon": (
                    draft["horizon"]
                ),
                "target_date": (
                    draft["target_date"]
                ),
                "candidate_id": (
                    draft["candidate_id"]
                ),
                "prediction_raw": (
                    draft["prediction_raw"]
                ),
                "prediction_rounded": (
                    draft[
                        "prediction_rounded"
                    ]
                ),
                "planned_beds": (
                    draft["planned_beds"]
                ),
                "predicted_utilization_pct": (
                    draft[
                        "predicted_utilization_pct"
                    ]
                ),
                "capacity_alert": (
                    draft["capacity_alert"]
                ),
                "capacity_excess_beds": (
                    draft[
                        "capacity_excess_beds"
                    ]
                ),
                "feature_version": (
                    draft["feature_version"]
                ),
                "data_version": (
                    draft["data_version"]
                ),
                "confirmed_by": (
                    confirmed_by
                ),
            },
        )

    def mark_draft_confirmed(
        self,
        draft_id: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.forecast_drafts
                SET
                    status='CONFIRMED',
                    confirmed_at=SYSUTCDATETIME()
                WHERE
                    draft_id=:draft_id
                    AND status='DRAFT'
                """
            ),
            {
                "draft_id": draft_id
            },
        )