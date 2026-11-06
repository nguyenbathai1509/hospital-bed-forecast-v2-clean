from __future__ import annotations

import json

from sqlalchemy import text

from src.db.engine import create_sql_engine


EXPECTED_ACTIVE = {
    1: "RF",
    3: "SVR",
}


def main() -> int:
    engine = create_sql_engine()

    with engine.connect() as conn:
        latest_business_date = conn.execute(
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

        changes = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        change_id,
                        business_date,
                        change_kind,
                        status,
                        requested_by,
                        change_reason,
                        confirmation_mode,
                        created_at,
                        confirmed_at
                    FROM dbo.production_changes
                    ORDER BY created_at, change_id
                    """
                )
            ).mappings().all()
        ]

        items = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        pci.change_id,
                        pci.horizon,
                        pci.from_candidate_id,
                        pci.to_candidate_id,
                        mc.model_family AS to_model_family,
                        pci.effect,
                        pci.effective_from_business_date,
                        pci.daily_lock_present,
                        pci.applied_at
                    FROM dbo.production_change_items pci
                    JOIN dbo.model_candidates mc
                      ON mc.candidate_id=pci.to_candidate_id
                    ORDER BY pci.change_id, pci.horizon
                    """
                )
            ).mappings().all()
        ]

        active = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        pm.horizon,
                        pm.candidate_id,
                        mc.model_family,
                        pm.slot_status,
                        pm.effective_from_business_date,
                        mc.registry_status,
                        mc.is_recommended
                    FROM dbo.production_models pm
                    JOIN dbo.model_candidates mc
                      ON mc.candidate_id=pm.candidate_id
                    WHERE pm.slot_status='ACTIVE'
                    ORDER BY pm.horizon
                    """
                )
            ).mappings().all()
        ]

        scheduled = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT
                        pm.horizon,
                        pm.candidate_id,
                        mc.model_family,
                        pm.effective_from_business_date
                    FROM dbo.production_models pm
                    JOIN dbo.model_candidates mc
                      ON mc.candidate_id=pm.candidate_id
                    WHERE pm.slot_status='SCHEDULED'
                    ORDER BY pm.horizon
                    """
                )
            ).mappings().all()
        ]

        daily_lock_count = int(
            conn.execute(text("SELECT COUNT(*) FROM dbo.daily_model_locks")).scalar_one()
        )

        normal_change_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.production_changes
                    WHERE
                        business_date=:business_date
                        AND change_kind='NORMAL_PROMOTION'
                        AND status='COMMITTED'
                    """
                ),
                {"business_date": latest_business_date},
            ).scalar_one()
        )

        quota_index_exists = bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM sys.indexes
                    WHERE
                        object_id=OBJECT_ID('dbo.production_changes')
                        AND name='UX_production_changes_one_normal_per_business_date'
                    """
                )
            ).scalar()
        )

    active_by_horizon = {
        int(row["horizon"]): row
        for row in active
    }

    report = {
        "latest_business_date": latest_business_date,
        "migrations": migrations,
        "production_change_count": len(changes),
        "production_changes": changes,
        "production_change_item_count": len(items),
        "production_change_items": items,
        "active_production_count": len(active),
        "active_production": active,
        "scheduled_production_count": len(scheduled),
        "scheduled_production": scheduled,
        "daily_model_lock_count": daily_lock_count,
        "normal_change_count_for_business_date": normal_change_count,
        "normal_change_quota_unique_index": quota_index_exists,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    initial_items = [
        row
        for row in items
        if row["effect"] == "IMMEDIATE"
        and bool(row["daily_lock_present"]) is False
    ]

    ok = (
        "005_production_promotion.sql" in migrations
        and latest_business_date is not None
        and normal_change_count == 1
        and quota_index_exists
        and len(active) == 2
        and active_by_horizon.get(1, {}).get("model_family") == EXPECTED_ACTIVE[1]
        and active_by_horizon.get(3, {}).get("model_family") == EXPECTED_ACTIVE[3]
        and all(
            active_by_horizon[h].get("registry_status") == "PRODUCTION"
            for h in (1, 3)
        )
        and len(scheduled) == 0
        and len(initial_items) >= 2
        and {
            int(row["horizon"])
            for row in initial_items
        } >= {1, 3}
        and all(row["applied_at"] is not None for row in initial_items)
    )

    print("\nV2-16 VERIFY: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())