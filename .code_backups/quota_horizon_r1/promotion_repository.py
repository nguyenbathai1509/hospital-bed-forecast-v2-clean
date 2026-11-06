from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.promotion.contracts import ProductionCandidate


class ProductionRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def latest_data_ready_business_date(self) -> date | None:
        return self.conn.execute(
            text(
                """
                SELECT TOP 1 business_date
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).scalar()

    def normal_change_exists(self, business_date: date) -> bool:
        value = self.conn.execute(
            text(
                """
                SELECT TOP 1 1
                FROM dbo.production_changes
                WHERE
                    business_date=:business_date
                    AND change_kind='NORMAL_PROMOTION'
                    AND status='COMMITTED'
                """
            ),
            {"business_date": business_date},
        ).scalar()

        return value is not None

    def daily_lock_exists(
        self,
        business_date: date,
        horizon: int,
    ) -> bool:
        value = self.conn.execute(
            text(
                """
                SELECT TOP 1 1
                FROM dbo.daily_model_locks
                WHERE origin_date=:business_date AND horizon=:horizon
                """
            ),
            {
                "business_date": business_date,
                "horizon": horizon,
            },
        ).scalar()

        return value is not None

    def get_candidate(
        self,
        candidate_id: str,
    ) -> ProductionCandidate | None:
        row = self.conn.execute(
            text(
                """
                SELECT
                    candidate_id,
                    horizon,
                    model_family,
                    mae,
                    run_id,
                    registry_status,
                    is_recommended
                FROM dbo.model_candidates
                WHERE candidate_id=:candidate_id
                """
            ),
            {"candidate_id": candidate_id},
        ).mappings().first()

        if row is None:
            return None

        if row["mae"] is None:
            raise ValueError(
                f"Candidate {candidate_id} has no MAE"
            )

        return ProductionCandidate(
            candidate_id=row["candidate_id"],
            horizon=int(row["horizon"]),
            model_family=row["model_family"],
            mae=float(row["mae"]),
            run_id=row["run_id"],
            registry_status=row["registry_status"],
            is_recommended=bool(
                row["is_recommended"]
            ),
        )

    def latest_recommended_candidate(
        self,
        horizon: int,
    ) -> tuple[
        ProductionCandidate,
        dict,
    ] | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    mr.recommendation_id,
                    mr.action,
                    mr.recommended_candidate_id
                FROM dbo.model_recommendations mr
                JOIN dbo.training_runs tr
                    ON tr.run_id = mr.run_id
                WHERE mr.horizon=:horizon
                ORDER BY tr.completed_at DESC, mr.created_at DESC
                """
            ),
            {"horizon": horizon},
        ).mappings().first()

        if row is None:
            return None

        candidate = self.get_candidate(
            row["recommended_candidate_id"]
        )

        if candidate is None:
            raise RuntimeError(
                "Recommendation points to missing candidate: "
                f"{row['recommended_candidate_id']}"
            )

        return (
            candidate,
            {
                "recommendation_id": (
                    row["recommendation_id"]
                ),
                "action": row["action"],
            },
        )

    def active_production(
        self,
        horizon: int,
    ) -> ProductionCandidate | None:
        candidate_id = self.conn.execute(
            text(
                """
                SELECT TOP 1 candidate_id
                FROM dbo.production_models
                WHERE horizon=:horizon AND slot_status='ACTIVE'
                ORDER BY production_id DESC
                """
            ),
            {"horizon": horizon},
        ).scalar()

        if candidate_id is None:
            return None

        return self.get_candidate(
            candidate_id
        )

    def scheduled_production(
        self,
        horizon: int,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    production_id,
                    candidate_id,
                    effective_from_business_date
                FROM dbo.production_models
                WHERE horizon=:horizon AND slot_status='SCHEDULED'
                ORDER BY production_id DESC
                """
            ),
            {"horizon": horizon},
        ).mappings().first()

        return (
            None
            if row is None
            else dict(row)
        )

    def previous_retired_candidate(
        self,
        horizon: int,
        current_candidate_id: str,
    ) -> ProductionCandidate | None:
        candidate_id = self.conn.execute(
            text(
                """
                SELECT TOP 1 candidate_id
                FROM dbo.production_models
                WHERE
                    horizon=:horizon
                    AND slot_status='RETIRED'
                    AND candidate_id<>:current_candidate_id
                ORDER BY
                    COALESCE(
                        effective_to_business_date,
                        effective_from_business_date
                    ) DESC,
                    production_id DESC
                """
            ),
            {
                "horizon": horizon,
                "current_candidate_id": (
                    current_candidate_id
                ),
            },
        ).scalar()

        if candidate_id is None:
            return None

        return self.get_candidate(
            candidate_id
        )

    def insert_change_header(
        self,
        *,
        change_id: str,
        business_date: date,
        change_kind: str,
        requested_by: str,
        reason: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.production_changes
                (
                    change_id,
                    business_date,
                    change_kind,
                    status,
                    requested_by,
                    change_reason,
                    confirmation_mode,
                    created_at,
                    confirmed_at
                )
                VALUES
                (
                    :change_id,
                    :business_date,
                    :change_kind,
                    'COMMITTED',
                    :requested_by,
                    :reason,
                    'EXPLICIT_TEXT',
                    SYSUTCDATETIME(),
                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "change_id": change_id,
                "business_date": (
                    business_date
                ),
                "change_kind": (
                    change_kind
                ),
                "requested_by": (
                    requested_by
                ),
                "reason": reason,
            },
        )

    def insert_change_item(
        self,
        *,
        change_id: str,
        horizon: int,
        from_candidate_id: str | None,
        to_candidate_id: str,
        effect: str,
        effective_from_business_date: date,
        daily_lock_present: bool,
        applied_now: bool,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.production_change_items
                (
                    change_id,
                    horizon,
                    from_candidate_id,
                    to_candidate_id,
                    effect,
                    effective_from_business_date,
                    daily_lock_present,
                    applied_at
                )
                VALUES
                (
                    :change_id,
                    :horizon,
                    :from_candidate_id,
                    :to_candidate_id,
                    :effect,
                    :effective_from_business_date,
                    :daily_lock_present,
                    CASE
                        WHEN :applied_now=1
                        THEN SYSUTCDATETIME()
                        ELSE NULL
                    END
                )
                """
            ),
            {
                "change_id": change_id,
                "horizon": horizon,
                "from_candidate_id": (
                    from_candidate_id
                ),
                "to_candidate_id": (
                    to_candidate_id
                ),
                "effect": effect,
                "effective_from_business_date": (
                    effective_from_business_date
                ),
                "daily_lock_present": int(
                    daily_lock_present
                ),
                "applied_now": int(
                    applied_now
                ),
            },
        )

    def _restore_nonproduction_registry_status(
        self,
        candidate_id: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    registry_status=(
                        CASE
                            WHEN is_recommended=1
                            THEN 'RECOMMENDED'
                            ELSE 'CANDIDATE'
                        END
                    ),
                    updated_at=SYSUTCDATETIME()
                WHERE candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                )
            },
        )

    def _archive_candidate(
        self,
        candidate_id: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    registry_status='ARCHIVED',
                    updated_at=SYSUTCDATETIME()
                WHERE candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                )
            },
        )

    def activate_candidate(
        self,
        *,
        horizon: int,
        candidate_id: str,
        business_date: date,
        requested_by: str,
        reason: str,
    ) -> None:
        active = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    production_id,
                    candidate_id
                FROM dbo.production_models
                WHERE
                    horizon=:horizon
                    AND slot_status='ACTIVE'
                ORDER BY production_id DESC
                """
            ),
            {"horizon": horizon},
        ).mappings().first()

        if active is not None:
            self.conn.execute(
                text(
                    """
                    UPDATE dbo.production_models
                    SET
                        slot_status='RETIRED',
                        effective_to_business_date=:effective_to
                    WHERE production_id=:production_id
                    """
                ),
                {
                    "production_id": (
                        active["production_id"]
                    ),
                    "effective_to": (
                        business_date
                    ),
                },
            )

            self._archive_candidate(
                active["candidate_id"]
            )

        scheduled = (
            self.scheduled_production(
                horizon
            )
        )

        if scheduled is not None:
            self.conn.execute(
                text(
                    """
                    UPDATE dbo.production_models
                    SET
                        slot_status='RETIRED',
                        effective_to_business_date=:effective_to
                    WHERE production_id=:production_id
                    """
                ),
                {
                    "production_id": (
                        scheduled["production_id"]
                    ),
                    "effective_to": (
                        scheduled[
                            "effective_from_business_date"
                        ]
                    ),
                },
            )

            self._restore_nonproduction_registry_status(
                scheduled["candidate_id"]
            )

        self.conn.execute(
            text(
                """
                INSERT INTO dbo.production_models
                (
                    horizon,
                    candidate_id,
                    slot_status,
                    effective_from_business_date,
                    effective_to_business_date,
                    promoted_by,
                    promotion_reason,
                    created_at
                )
                VALUES
                (
                    :horizon,
                    :candidate_id,
                    'ACTIVE',
                    :business_date,
                    NULL,
                    :requested_by,
                    :reason,
                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "horizon": horizon,
                "candidate_id": (
                    candidate_id
                ),
                "business_date": (
                    business_date
                ),
                "requested_by": (
                    requested_by
                ),
                "reason": reason,
            },
        )

        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    registry_status='PRODUCTION',
                    updated_at=SYSUTCDATETIME()
                WHERE candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                )
            },
        )

    def schedule_candidate(
        self,
        *,
        horizon: int,
        candidate_id: str,
        effective_from_business_date: date,
        requested_by: str,
        reason: str,
    ) -> None:
        existing = (
            self.scheduled_production(
                horizon
            )
        )

        if existing is not None:
            self.conn.execute(
                text(
                    """
                    UPDATE dbo.production_models
                    SET
                        slot_status='RETIRED',
                        effective_to_business_date=:effective_to
                    WHERE production_id=:production_id
                    """
                ),
                {
                    "production_id": (
                        existing["production_id"]
                    ),
                    "effective_to": (
                        existing[
                            "effective_from_business_date"
                        ]
                    ),
                },
            )

            self._restore_nonproduction_registry_status(
                existing["candidate_id"]
            )

        self.conn.execute(
            text(
                """
                INSERT INTO dbo.production_models
                (
                    horizon,
                    candidate_id,
                    slot_status,
                    effective_from_business_date,
                    effective_to_business_date,
                    promoted_by,
                    promotion_reason,
                    created_at
                )
                VALUES
                (
                    :horizon,
                    :candidate_id,
                    'SCHEDULED',
                    :effective_from_business_date,
                    NULL,
                    :requested_by,
                    :reason,
                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "horizon": horizon,
                "candidate_id": (
                    candidate_id
                ),
                "effective_from_business_date": (
                    effective_from_business_date
                ),
                "requested_by": (
                    requested_by
                ),
                "reason": reason,
            },
        )

        self.conn.execute(
            text(
                """
                UPDATE dbo.model_candidates
                SET
                    registry_status='SCHEDULED',
                    updated_at=SYSUTCDATETIME()
                WHERE candidate_id=:candidate_id
                """
            ),
            {
                "candidate_id": (
                    candidate_id
                )
            },
        )

    def activate_due_scheduled(
        self,
        business_date: date,
    ) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT
                    production_id,
                    horizon,
                    candidate_id,
                    effective_from_business_date,
                    promoted_by,
                    promotion_reason
                FROM dbo.production_models
                WHERE
                    slot_status='SCHEDULED'
                    AND effective_from_business_date<=:business_date
                ORDER BY horizon, production_id
                """
            ),
            {
                "business_date": (
                    business_date
                )
            },
        ).mappings().all()

        activated: list[dict] = []

        for row in rows:
            horizon = int(
                row["horizon"]
            )

            if self.daily_lock_exists(
                business_date,
                horizon,
            ):
                continue

            active = self.conn.execute(
                text(
                    """
                    SELECT TOP 1
                        production_id,
                        candidate_id
                    FROM dbo.production_models
                    WHERE
                        horizon=:horizon
                        AND slot_status='ACTIVE'
                    ORDER BY production_id DESC
                    """
                ),
                {
                    "horizon": (
                        horizon
                    )
                },
            ).mappings().first()

            if active is not None:
                self.conn.execute(
                    text(
                        """
                        UPDATE dbo.production_models
                        SET
                            slot_status='RETIRED',
                            effective_to_business_date=:effective_to
                        WHERE production_id=:production_id
                        """
                    ),
                    {
                        "production_id": (
                            active["production_id"]
                        ),
                        "effective_to": (
                            business_date
                        ),
                    },
                )

                self._archive_candidate(
                    active["candidate_id"]
                )

            self.conn.execute(
                text(
                    """
                    UPDATE dbo.production_models
                    SET slot_status='ACTIVE'
                    WHERE production_id=:production_id
                    """
                ),
                {
                    "production_id": (
                        row["production_id"]
                    )
                },
            )

            self.conn.execute(
                text(
                    """
                    UPDATE dbo.model_candidates
                    SET
                        registry_status='PRODUCTION',
                        updated_at=SYSUTCDATETIME()
                    WHERE candidate_id=:candidate_id
                    """
                ),
                {
                    "candidate_id": (
                        row["candidate_id"]
                    )
                },
            )

            self.conn.execute(
                text(
                    """
                    UPDATE pci
                    SET
                        applied_at=COALESCE(
                            applied_at,
                            SYSUTCDATETIME()
                        )
                    FROM dbo.production_change_items pci
                    WHERE
                        pci.horizon=:horizon
                        AND pci.to_candidate_id=:candidate_id
                        AND pci.effect='NEXT_CYCLE'
                        AND pci.applied_at IS NULL
                    """
                ),
                {
                    "horizon": horizon,
                    "candidate_id": (
                        row["candidate_id"]
                    ),
                },
            )

            activated.append(
                {
                    "horizon": horizon,
                    "candidate_id": (
                        row["candidate_id"]
                    ),
                    "effective_from_business_date": str(
                        row[
                            "effective_from_business_date"
                        ]
                    ),
                }
            )

        return activated