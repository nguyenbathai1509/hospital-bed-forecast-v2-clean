from __future__ import annotations

from datetime import datetime, timezone
import uuid

from src.db.engine import create_sql_engine
from src.promotion.contracts import (
    PROMOTION_CONFIRMATION_PHRASE,
    ROLLBACK_CONFIRMATION_PHRASE,
    PromotionPlan,
    PromotionPlanItem,
)
from src.promotion.engine import (
    resolve_effect,
    validate_horizons,
)
from src.promotion.repository import (
    ProductionRepository,
)


def _new_change_id(
    prefix: str,
) -> str:
    return (
        f"{prefix}_"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


def plan_promotion(
    horizons=(1, 3),
) -> PromotionPlan:
    resolved_horizons = (
        validate_horizons(
            horizons
        )
    )

    engine = (
        create_sql_engine()
    )

    with engine.connect() as conn:
        repo = (
            ProductionRepository(
                conn
            )
        )

        business_date = (
            repo.latest_data_ready_business_date()
        )

        if business_date is None:
            raise RuntimeError(
                "No DATA_READY business_date exists"
            )

        items: list[
            PromotionPlanItem
        ] = []

        for horizon in resolved_horizons:
            recommendation = (
                repo.latest_recommended_candidate(
                    horizon
                )
            )

            if recommendation is None:
                raise RuntimeError(
                    f"No recommendation exists for H+{horizon}; "
                    "run V2-15 first"
                )

            (
                candidate,
                recommendation_meta,
            ) = recommendation

            current = (
                repo.active_production(
                    horizon
                )
            )

            if (
                current is not None
                and current.candidate_id
                == candidate.candidate_id
            ):
                continue

            lock_present = (
                repo.daily_lock_exists(
                    business_date,
                    horizon,
                )
            )

            (
                effect,
                effective_from,
            ) = resolve_effect(
                business_date=business_date,
                daily_lock_present=(
                    lock_present
                ),
            )

            if (
                lock_present
                and current is None
            ):
                raise RuntimeError(
                    f"H+{horizon} has a daily model lock "
                    "but no ACTIVE Production; "
                    "manual investigation is required"
                )

            items.append(
                PromotionPlanItem(
                    horizon=horizon,
                    from_candidate_id=(
                        None
                        if current is None
                        else current.candidate_id
                    ),
                    from_model_family=(
                        None
                        if current is None
                        else current.model_family
                    ),
                    to_candidate_id=(
                        candidate.candidate_id
                    ),
                    to_model_family=(
                        candidate.model_family
                    ),
                    to_mae=(
                        candidate.mae
                    ),
                    recommendation_id=(
                        recommendation_meta[
                            "recommendation_id"
                        ]
                    ),
                    recommendation_action=(
                        recommendation_meta[
                            "action"
                        ]
                    ),
                    effect=effect,
                    effective_from_business_date=(
                        effective_from
                    ),
                    daily_lock_present=(
                        lock_present
                    ),
                )
            )

        return PromotionPlan(
            business_date=(
                business_date
            ),
            change_kind=(
                "NORMAL_PROMOTION"
            ),
            quota_used=(
                repo.normal_change_exists(
                    business_date
                )
            ),
            items=tuple(items),
            confirmation_phrase=(
                PROMOTION_CONFIRMATION_PHRASE
            ),
        )


def execute_promotion(
    *,
    horizons=(1, 3),
    confirmation: str | None,
    requested_by: str = "manual",
    reason: str = (
        "Promote recommended model(s) to Production."
    ),
) -> dict:
    plan = plan_promotion(
        horizons
    )

    if not plan.has_changes:
        return {
            "status": "NO_CHANGE",
            "message": (
                "Requested Recommended models "
                "are already ACTIVE Production."
            ),
            "plan": plan.as_dict(),
        }

    if (
        confirmation
        != PROMOTION_CONFIRMATION_PHRASE
    ):
        return {
            "status": (
                "CONFIRMATION_REQUIRED"
            ),
            "message": (
                "Review current Production, candidate, "
                "effect, and business_date. "
                "Re-run with --confirm "
                f"{PROMOTION_CONFIRMATION_PHRASE} "
                "to commit."
            ),
            "plan": plan.as_dict(),
        }

    if plan.quota_used:
        raise RuntimeError(
            "NORMAL Production Change quota "
            "already used for "
            f"business_date={plan.business_date}. "
            "Only an audited emergency rollback "
            "may bypass this quota."
        )

    if not reason.strip():
        raise ValueError(
            "Promotion reason is required"
        )

    change_id = _new_change_id(
        "PROMOTE"
    )

    engine = (
        create_sql_engine()
    )

    with engine.begin() as conn:
        repo = (
            ProductionRepository(
                conn
            )
        )

        business_date = (
            repo.latest_data_ready_business_date()
        )

        if (
            business_date
            != plan.business_date
        ):
            raise RuntimeError(
                "business_date changed after "
                "confirmation preview; "
                "re-plan Promotion"
            )

        if repo.normal_change_exists(
            business_date
        ):
            raise RuntimeError(
                "NORMAL Production Change quota "
                f"already used for {business_date}"
            )

        repo.insert_change_header(
            change_id=change_id,
            business_date=(
                business_date
            ),
            change_kind=(
                "NORMAL_PROMOTION"
            ),
            requested_by=(
                requested_by
            ),
            reason=reason,
        )

        for item in plan.items:
            current = (
                repo.active_production(
                    item.horizon
                )
            )

            recommendation = (
                repo.latest_recommended_candidate(
                    item.horizon
                )
            )

            if recommendation is None:
                raise RuntimeError(
                    "Recommendation disappeared "
                    f"for H+{item.horizon}"
                )

            candidate, _ = (
                recommendation
            )

            expected_current = (
                None
                if current is None
                else current.candidate_id
            )

            if (
                expected_current
                != item.from_candidate_id
            ):
                raise RuntimeError(
                    "Production changed for "
                    f"H+{item.horizon} "
                    "after preview; re-plan"
                )

            if (
                candidate.candidate_id
                != item.to_candidate_id
            ):
                raise RuntimeError(
                    "Recommendation changed for "
                    f"H+{item.horizon} "
                    "after preview; re-plan"
                )

            lock_present = (
                repo.daily_lock_exists(
                    business_date,
                    item.horizon,
                )
            )

            (
                effect,
                effective_from,
            ) = resolve_effect(
                business_date=(
                    business_date
                ),
                daily_lock_present=(
                    lock_present
                ),
            )

            if (
                effect != item.effect
                or effective_from
                != item.effective_from_business_date
            ):
                raise RuntimeError(
                    "Official/daily lock state "
                    "changed for "
                    f"H+{item.horizon}; re-plan"
                )

            repo.insert_change_item(
                change_id=change_id,
                horizon=item.horizon,
                from_candidate_id=(
                    item.from_candidate_id
                ),
                to_candidate_id=(
                    item.to_candidate_id
                ),
                effect=effect,
                effective_from_business_date=(
                    effective_from
                ),
                daily_lock_present=(
                    lock_present
                ),
                applied_now=(
                    effect
                    == "IMMEDIATE"
                ),
            )

            if effect == "IMMEDIATE":
                repo.activate_candidate(
                    horizon=(
                        item.horizon
                    ),
                    candidate_id=(
                        item.to_candidate_id
                    ),
                    business_date=(
                        business_date
                    ),
                    requested_by=(
                        requested_by
                    ),
                    reason=reason,
                )

            else:
                repo.schedule_candidate(
                    horizon=(
                        item.horizon
                    ),
                    candidate_id=(
                        item.to_candidate_id
                    ),
                    effective_from_business_date=(
                        effective_from
                    ),
                    requested_by=(
                        requested_by
                    ),
                    reason=reason,
                )

    return {
        "status": "COMPLETED",
        "change_id": change_id,
        "business_date": (
            plan.business_date.isoformat()
        ),
        "change_kind": (
            "NORMAL_PROMOTION"
        ),
        "items": [
            item.as_dict()
            for item
            in plan.items
        ],
    }


def plan_emergency_rollback(
    horizon: int,
) -> PromotionPlan:
    resolved_horizon = (
        validate_horizons(
            [horizon]
        )[0]
    )

    engine = (
        create_sql_engine()
    )

    with engine.connect() as conn:
        repo = (
            ProductionRepository(
                conn
            )
        )

        business_date = (
            repo.latest_data_ready_business_date()
        )

        if business_date is None:
            raise RuntimeError(
                "No DATA_READY business_date exists"
            )

        current = (
            repo.active_production(
                resolved_horizon
            )
        )

        if current is None:
            raise RuntimeError(
                "No ACTIVE Production exists "
                f"for H+{resolved_horizon}"
            )

        previous = (
            repo.previous_retired_candidate(
                resolved_horizon,
                current.candidate_id,
            )
        )

        if previous is None:
            raise RuntimeError(
                "No previous RETIRED Production "
                "candidate exists for "
                f"H+{resolved_horizon}"
            )

        lock_present = (
            repo.daily_lock_exists(
                business_date,
                resolved_horizon,
            )
        )

        (
            effect,
            effective_from,
        ) = resolve_effect(
            business_date=(
                business_date
            ),
            daily_lock_present=(
                lock_present
            ),
        )

        return PromotionPlan(
            business_date=(
                business_date
            ),
            change_kind=(
                "EMERGENCY_ROLLBACK"
            ),
            quota_used=(
                repo.normal_change_exists(
                    business_date
                )
            ),
            items=(
                PromotionPlanItem(
                    horizon=(
                        resolved_horizon
                    ),
                    from_candidate_id=(
                        current.candidate_id
                    ),
                    from_model_family=(
                        current.model_family
                    ),
                    to_candidate_id=(
                        previous.candidate_id
                    ),
                    to_model_family=(
                        previous.model_family
                    ),
                    to_mae=(
                        previous.mae
                    ),
                    recommendation_id=None,
                    recommendation_action=None,
                    effect=effect,
                    effective_from_business_date=(
                        effective_from
                    ),
                    daily_lock_present=(
                        lock_present
                    ),
                ),
            ),
            confirmation_phrase=(
                ROLLBACK_CONFIRMATION_PHRASE
            ),
        )


def execute_emergency_rollback(
    *,
    horizon: int,
    confirmation: str | None,
    requested_by: str = "manual",
    reason: str,
) -> dict:
    plan = (
        plan_emergency_rollback(
            horizon
        )
    )

    if (
        confirmation
        != ROLLBACK_CONFIRMATION_PHRASE
    ):
        return {
            "status": (
                "CONFIRMATION_REQUIRED"
            ),
            "message": (
                "Emergency rollback bypasses "
                "the normal daily Production "
                "Change quota. Re-run with "
                "--confirm "
                f"{ROLLBACK_CONFIRMATION_PHRASE} "
                "after review."
            ),
            "plan": plan.as_dict(),
        }

    if len(
        reason.strip()
    ) < 10:
        raise ValueError(
            "Emergency rollback requires "
            "an explicit audit reason "
            "of at least 10 characters"
        )

    change_id = _new_change_id(
        "ROLLBACK"
    )

    item = plan.items[0]

    engine = (
        create_sql_engine()
    )

    with engine.begin() as conn:
        repo = (
            ProductionRepository(
                conn
            )
        )

        business_date = (
            repo.latest_data_ready_business_date()
        )

        if (
            business_date
            != plan.business_date
        ):
            raise RuntimeError(
                "business_date changed; "
                "re-plan rollback"
            )

        current = (
            repo.active_production(
                item.horizon
            )
        )

        if (
            current is None
            or current.candidate_id
            != item.from_candidate_id
        ):
            raise RuntimeError(
                "ACTIVE Production changed "
                "after rollback preview; "
                "re-plan"
            )

        previous = (
            repo.previous_retired_candidate(
                item.horizon,
                current.candidate_id,
            )
        )

        if (
            previous is None
            or previous.candidate_id
            != item.to_candidate_id
        ):
            raise RuntimeError(
                "Rollback target changed "
                "after preview; re-plan"
            )

        lock_present = (
            repo.daily_lock_exists(
                business_date,
                item.horizon,
            )
        )

        (
            effect,
            effective_from,
        ) = resolve_effect(
            business_date=(
                business_date
            ),
            daily_lock_present=(
                lock_present
            ),
        )

        if (
            effect != item.effect
            or effective_from
            != item.effective_from_business_date
        ):
            raise RuntimeError(
                "Official/daily lock state "
                "changed; re-plan rollback"
            )

        repo.insert_change_header(
            change_id=change_id,
            business_date=(
                business_date
            ),
            change_kind=(
                "EMERGENCY_ROLLBACK"
            ),
            requested_by=(
                requested_by
            ),
            reason=reason,
        )

        repo.insert_change_item(
            change_id=change_id,
            horizon=item.horizon,
            from_candidate_id=(
                item.from_candidate_id
            ),
            to_candidate_id=(
                item.to_candidate_id
            ),
            effect=effect,
            effective_from_business_date=(
                effective_from
            ),
            daily_lock_present=(
                lock_present
            ),
            applied_now=(
                effect == "IMMEDIATE"
            ),
        )

        if effect == "IMMEDIATE":
            repo.activate_candidate(
                horizon=item.horizon,
                candidate_id=(
                    item.to_candidate_id
                ),
                business_date=(
                    business_date
                ),
                requested_by=(
                    requested_by
                ),
                reason=reason,
            )

        else:
            repo.schedule_candidate(
                horizon=item.horizon,
                candidate_id=(
                    item.to_candidate_id
                ),
                effective_from_business_date=(
                    effective_from
                ),
                requested_by=(
                    requested_by
                ),
                reason=reason,
            )

    return {
        "status": "COMPLETED",
        "change_id": change_id,
        "business_date": (
            plan.business_date.isoformat()
        ),
        "change_kind": (
            "EMERGENCY_ROLLBACK"
        ),
        "items": [
            item.as_dict()
        ],
    }


def activate_due_scheduled_models(
    business_date,
) -> dict:
    engine = (
        create_sql_engine()
    )

    with engine.begin() as conn:
        activated = (
            ProductionRepository(
                conn
            ).activate_due_scheduled(
                business_date
            )
        )

    return {
        "status": "PASS",
        "business_date": str(
            business_date
        ),
        "activated_count": len(
            activated
        ),
        "activated": activated,
    }