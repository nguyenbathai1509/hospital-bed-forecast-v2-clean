from src.recommendation.config import (
    RecommendationPolicy,
)

from src.recommendation.contracts import (
    CandidateMetrics,
    DepartmentMetrics,
)

from src.recommendation.engine import (
    decide_recommendation,
    improvement_pct,
    rank_candidates,
)


def candidate(
    candidate_id: str,
    family: str,
    mae: float,
    *,
    horizon: int = 1,
    rmse: float = 3.0,
    wape: float = 5.0,
    bias: float = -0.5,
    p90: float = 4.0,
    max_error: float = 8.0,
    within2: float = 0.60,
    under_rate: float = 0.40,
    under_mae: float = 1.5,
):
    return CandidateMetrics(
        candidate_id=(
            candidate_id
        ),
        run_id="R1",
        horizon=horizon,
        model_family=family,
        mae=mae,
        rmse=rmse,
        wape=wape,
        r2=0.5,
        bias=bias,
        p90_abs_error=p90,
        max_abs_error=max_error,
        within_2_rate=within2,
        underprediction_rate=(
            under_rate
        ),
        underprediction_mae=(
            under_mae
        ),
        split_spec={
            "test_start": (
                "2026-05-25"
            ),
            "test_end": (
                "2026-06-30"
            ),
        },
    )


def department(
    candidate_id: str,
    dep: int,
    mae: float = 2.0,
):
    return DepartmentMetrics(
        candidate_id=(
            candidate_id
        ),
        department_id=dep,
        sample_count=37,
        mae=mae,
        rmse=3.0,
        wape=5.0,
        r2=0.5,
        bias=-0.5,
        p90_abs_error=4.0,
        max_abs_error=8.0,
        within_2_rate=0.60,
        underprediction_rate=0.40,
        underprediction_mae=1.5,
    )


def dept_map(
    *candidate_ids: str,
):
    return {
        cid: {
            343: department(
                cid,
                343,
            ),
            344: department(
                cid,
                344,
            ),
        }
        for cid in candidate_ids
    }


def test_rank_uses_mae_as_primary_metric():
    rows = [
        candidate(
            "RF",
            "RF",
            2.25,
        ),
        candidate(
            "SVR",
            "SVR",
            2.24,
        ),
        candidate(
            "XGB",
            "XGBOOST",
            2.40,
        ),
    ]

    ranked = (
        rank_candidates(
            rows
        )
    )

    assert [
        row.candidate_id
        for row
        in ranked
    ] == [
        "SVR",
        "RF",
        "XGB",
    ]


def test_improvement_formula_matches_v2_master():
    value = (
        improvement_pct(
            2.254877826852109,
            2.2481808686616898,
        )
    )

    assert (
        0.29
        < value
        < 0.31
    )


def test_keep_when_improvement_is_below_one_percent():
    champion = candidate(
        "RF",
        "RF",
        2.254877826852109,
    )

    challenger = candidate(
        "SVR",
        "SVR",
        2.2481808686616898,
    )

    decision = (
        decide_recommendation(
            ranked_candidates=[
                challenger,
                champion,
            ],
            champion=champion,
            champion_source=(
                "BOOTSTRAP_REFERENCE"
            ),
            metrics_by_candidate_department=(
                dept_map(
                    "RF",
                    "SVR",
                )
            ),
            policy=(
                RecommendationPolicy(
                    minimum_improvement_pct=1.0
                )
            ),
        )
    )

    assert (
        decision.action
        == "KEEP"
    )

    assert (
        decision.recommended_candidate_id
        == "RF"
    )

    assert (
        decision.reason_code
        == "KEEP_MINIMUM_IMPROVEMENT"
    )


def test_promote_when_improvement_and_guardrails_pass():
    champion = candidate(
        "RF",
        "RF",
        3.0,
    )

    challenger = candidate(
        "SVR",
        "SVR",
        2.7,
    )

    decision = (
        decide_recommendation(
            ranked_candidates=[
                challenger,
                champion,
            ],
            champion=champion,
            champion_source=(
                "PRODUCTION"
            ),
            metrics_by_candidate_department=(
                dept_map(
                    "RF",
                    "SVR",
                )
            ),
            policy=(
                RecommendationPolicy(
                    minimum_improvement_pct=1.0
                )
            ),
        )
    )

    assert (
        decision.action
        == "PROMOTE"
    )

    assert (
        decision.recommended_candidate_id
        == "SVR"
    )

    assert (
        decision.guardrail_pass
    )


def test_guardrail_failure_keeps_champion_even_with_large_mae_gain():
    champion = candidate(
        "RF",
        "RF",
        3.0,
        within2=0.70,
    )

    challenger = candidate(
        "SVR",
        "SVR",
        2.5,
        within2=0.50,
    )

    decision = (
        decide_recommendation(
            ranked_candidates=[
                challenger,
                champion,
            ],
            champion=champion,
            champion_source=(
                "PRODUCTION"
            ),
            metrics_by_candidate_department=(
                dept_map(
                    "RF",
                    "SVR",
                )
            ),
            policy=(
                RecommendationPolicy(
                    minimum_improvement_pct=1.0
                )
            ),
        )
    )

    assert (
        decision.action
        == "KEEP"
    )

    assert (
        decision.recommended_candidate_id
        == "RF"
    )

    assert (
        not decision.guardrail_pass
    )

    assert (
        decision.reason_code
        == "KEEP_GUARDRAIL"
    )


def test_best_is_champion_returns_keep_without_artificial_improvement():
    champion = candidate(
        "SVR",
        "SVR",
        2.20,
        horizon=3,
    )

    challenger = candidate(
        "RF",
        "RF",
        2.40,
        horizon=3,
    )

    decision = (
        decide_recommendation(
            ranked_candidates=[
                champion,
                challenger,
            ],
            champion=champion,
            champion_source=(
                "BOOTSTRAP_REFERENCE"
            ),
            metrics_by_candidate_department=(
                dept_map(
                    "SVR",
                    "RF",
                )
            ),
            policy=(
                RecommendationPolicy()
            ),
        )
    )

    assert (
        decision.action
        == "KEEP"
    )

    assert (
        decision.best_candidate_id
        == "SVR"
    )

    assert (
        decision.recommended_candidate_id
        == "SVR"
    )

    assert (
        decision.improvement_pct
        == 0.0
    )

    assert (
        decision.reason_code
        == "BEST_IS_CHAMPION"
    )