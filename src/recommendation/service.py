from __future__ import annotations

from src.training.job_context import fence_training_job

from datetime import (
    datetime,
    timezone,
)

from src.db.engine import (
    create_sql_engine,
)

from src.recommendation.config import (
    BOOTSTRAP_CHAMPION_FAMILY,
    DEFAULT_POLICY,
    RecommendationPolicy,
)

from src.recommendation.engine import (
    rank_candidates,
)
from src.recommendation.backtest import (
    BACKTEST_VERSION,
    InsufficientComparisonData,
    backtest_recommendation,
)
from src.recommendation.contracts import RecommendationDecision

from src.recommendation.repository import (
    RecommendationRepository,
)


def _recommendation_id(
    run_id: str,
    horizon: int,
) -> str:
    return (
        f"REC_{run_id}_H{horizon}"
    )


def generate_recommendations(
    *,
    run_id: str | None = None,
    policy: RecommendationPolicy = (
        DEFAULT_POLICY
    ),
) -> dict:
    """Generate immutable V2 recommendation snapshots for H+1 and H+3.

    Recommended != Production. This service updates recommendation metadata only;
    it never writes dbo.production_models.
    """

    engine = (
        create_sql_engine()
    )

    with engine.connect() as conn:
        repo = (
            RecommendationRepository(
                conn
            )
        )

        training_run = (
            repo.latest_completed_training_run()
            if run_id is None
            else repo.get_training_run(
                run_id
            )
        )

        if training_run is None:
            raise RuntimeError(
                "No Training Run found "
                "for recommendation"
            )

        if (
            training_run["status"]
            != "COMPLETED"
        ):
            raise RuntimeError(
                "Recommendation requires "
                "a COMPLETED Training Run; "
                f"got "
                f"{training_run['status']}"
            )

        resolved_run_id = (
            training_run["run_id"]
        )

        existing = {
            horizon: (
                repo.get_existing_recommendation(
                    resolved_run_id,
                    horizon,
                )
            )
            for horizon in (
                1,
                3,
            )
        }

        if all(
            existing.values()
        ):
            return {
                "status": (
                    "ALREADY_RECOMMENDED"
                ),
                "run_id": (
                    resolved_run_id
                ),
                "business_date": str(
                    training_run[
                        "business_date"
                    ]
                ),
                "recommendations": [
                    existing[horizon]
                    for horizon
                    in (
                        1,
                        3,
                    )
                ],
            }

        if any(
            existing.values()
        ):
            raise RuntimeError(
                "Partial recommendation "
                "state detected for the "
                "Training Run. Manual "
                "investigation is required "
                "before retry."
            )

        candidates_by_horizon = {
            horizon: (
                repo.list_candidates_for_run_horizon(
                    resolved_run_id,
                    horizon,
                )
            )
            for horizon
            in (
                1,
                3,
            )
        }

        for (
            horizon,
            candidates,
        ) in (
            candidates_by_horizon.items()
        ):
            if len(
                candidates
            ) != 4:
                raise RuntimeError(
                    "Expected 4 candidates "
                    f"for H+{horizon}; "
                    f"got {len(candidates)}"
                )

        champion_by_horizon = {}
        champion_source_by_horizon = {}

        for horizon in (
            1,
            3,
        ):
            production_candidate_id = (
                repo.active_production_candidate_id(
                    horizon
                )
            )

            if (
                production_candidate_id
                is not None
            ):
                champion = (
                    repo.get_candidate_metrics(
                        production_candidate_id
                    )
                )

                if champion is None:
                    raise RuntimeError(
                        "ACTIVE Production "
                        "points to a missing "
                        "candidate: "
                        f"{production_candidate_id}"
                    )

                champion_by_horizon[
                    horizon
                ] = champion

                champion_source_by_horizon[
                    horizon
                ] = "PRODUCTION"

            else:
                family = (
                    BOOTSTRAP_CHAMPION_FAMILY[
                        horizon
                    ]
                )

                champion = (
                    repo.bootstrap_candidate(
                        resolved_run_id,
                        horizon,
                        family,
                    )
                )

                if champion is None:
                    raise RuntimeError(
                        "No active Production "
                        "and bootstrap Champion "
                        "is missing: "
                        f"H+{horizon} "
                        f"family={family}"
                    )

                champion_by_horizon[
                    horizon
                ] = champion

                champion_source_by_horizon[
                    horizon
                ] = (
                    "BOOTSTRAP_REFERENCE"
                )

    # Release the read connection before the CPU-intensive comparison.
    decisions, rankings, comparisons = {}, {}, {}
    for horizon in (1, 3):
        champion = champion_by_horizon[horizon]
        try:
            comparison = backtest_recommendation(
                run_id=resolved_run_id, candidates=candidates_by_horizon[horizon],
                champion=champion, champion_source=champion_source_by_horizon[horizon], policy=policy,
            )
            decisions[horizon] = comparison.decision
            rankings[horizon] = comparison.ranked
            comparisons[horizon] = comparison.evidence
        except InsufficientComparisonData as exc:
            ranked = rank_candidates(candidates_by_horizon[horizon])
            rankings[horizon] = ranked
            decisions[horizon] = RecommendationDecision(
                horizon=horizon, best_candidate_id=ranked[0].candidate_id,
                champion_candidate_id=champion.candidate_id,
                recommended_candidate_id=champion.candidate_id,
                champion_source=champion_source_by_horizon[horizon], action="KEEP",
                improvement_pct=0.0, minimum_improvement_pct=policy.minimum_improvement_pct,
                guardrail_pass=False, reason_code="KEEP_INSUFFICIENT_COMMON_WINDOW",
                reasons=(str(exc), "Chưa đủ bằng chứng so sánh; giữ mô hình tham chiếu hiện tại."),
                guardrails=(),
            )
            comparisons[horizon] = {
                "version": BACKTEST_VERSION, "status": "INSUFFICIENT_DATA", "reason": str(exc),
                "ranking_basis": "ORIGINAL_TEST_NOT_COMPARABLE", "decision_uses_audit": False,
            }

    with engine.begin() as conn:
        fence_training_job(conn)
        repo = (
            RecommendationRepository(
                conn
            )
        )

        # If the active model changed while backtesting, do not publish a
        # recommendation against a champion that is no longer current.
        for horizon in (1, 3):
            expected_active = (
                champion_by_horizon[horizon].candidate_id
                if champion_source_by_horizon[horizon] == "PRODUCTION" else None
            )
            if repo.active_production_candidate_id(horizon, for_update=True) != expected_active:
                raise RuntimeError("Production champion changed during backtest; retry recommendation")

        for horizon in (
            1,
            3,
        ):
            repo.save_recommendation(
                recommendation_id=(
                    _recommendation_id(
                        resolved_run_id,
                        horizon,
                    )
                ),
                run_id=(
                    resolved_run_id
                ),
                decision=(
                    decisions[horizon]
                ),
                ranked_candidates=(
                    rankings[horizon]
                ),
                policy=(
                    {**policy.as_dict(), "comparison": comparisons[horizon]}
                ),
            )

    return {
        "status": "COMPLETED",
        "run_id": (
            resolved_run_id
        ),
        "business_date": str(
            training_run[
                "business_date"
            ]
        ),
        "generated_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "policy": (
            policy.as_dict()
        ),
        "comparisons": {str(h): evidence for h, evidence in comparisons.items()},
        "recommendations": [
            decisions[
                horizon
            ].as_dict()
            for horizon
            in (
                1,
                3,
            )
        ],
        "rankings": {
            str(
                horizon
            ): [
                {
                    "rank": (
                        rank_no
                    ),
                    "candidate_id": (
                        candidate.candidate_id
                    ),
                    "model_family": (
                        candidate.model_family
                    ),
                    "mae": (
                        candidate.mae
                    ),
                    "rmse": (
                        candidate.rmse
                    ),
                    "wape": (
                        candidate.wape
                    ),
                    "bias": (
                        candidate.bias
                    ),
                }
                for (
                    rank_no,
                    candidate,
                )
                in enumerate(
                    rankings[
                        horizon
                    ],
                    start=1,
                )
            ]
            for horizon
            in (
                1,
                3,
            )
        },
    }
