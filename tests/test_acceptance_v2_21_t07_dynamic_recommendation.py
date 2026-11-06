from src.recommendation.config import RecommendationPolicy
from src.recommendation.contracts import (
    CandidateMetrics,
    DepartmentMetrics,
)
from src.recommendation.engine import (
    decide_recommendation,
    rank_candidates,
)


SPLIT = {
    "test_start": "2026-05-25",
    "test_end": "2026-06-30",
}


def candidate(
    candidate_id: str,
    family: str,
    mae: float,
):
    return CandidateMetrics(
        candidate_id=candidate_id,
        run_id="TRN_T07_TEST",
        horizon=1,
        model_family=family,
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
        split_spec=dict(SPLIT),
    )


def department_metrics(
    candidate_id: str,
    department_id: int,
):
    return DepartmentMetrics(
        candidate_id=candidate_id,
        department_id=department_id,
        sample_count=37,
        mae=2.0,
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


def metric_map(*candidate_ids: str):
    return {
        candidate_id: {
            343: department_metrics(
                candidate_id,
                343,
            ),
            344: department_metrics(
                candidate_id,
                344,
            ),
        }
        for candidate_id in candidate_ids
    }


def test_t07_recommendation_changes_when_metrics_winner_changes():
    policy = RecommendationPolicy(
        minimum_improvement_pct=1.0
    )

    # -------------------------------------------------
    # Scenario A:
    # RF đang tốt nhất và cũng là Champion.
    # -------------------------------------------------
    rf_a = candidate(
        "CAND_RF",
        "RF",
        2.0,
    )

    svr_a = candidate(
        "CAND_SVR",
        "SVR",
        2.5,
    )

    ranked_a = rank_candidates(
        [svr_a, rf_a]
    )

    assert (
        ranked_a[0].candidate_id
        == "CAND_RF"
    )

    decision_a = decide_recommendation(
        ranked_candidates=ranked_a,
        champion=rf_a,
        champion_source="PRODUCTION",
        metrics_by_candidate_department=(
            metric_map(
                "CAND_RF",
                "CAND_SVR",
            )
        ),
        policy=policy,
    )

    assert (
        decision_a.best_candidate_id
        == "CAND_RF"
    )

    assert decision_a.action == "KEEP"

    assert (
        decision_a.recommended_candidate_id
        == "CAND_RF"
    )

    # -------------------------------------------------
    # Scenario B:
    # Chỉ đổi metrics.
    # SVR bây giờ tốt hơn RF rõ ràng.
    # -------------------------------------------------
    rf_b = candidate(
        "CAND_RF",
        "RF",
        3.0,
    )

    svr_b = candidate(
        "CAND_SVR",
        "SVR",
        2.0,
    )

    ranked_b = rank_candidates(
        [rf_b, svr_b]
    )

    assert (
        ranked_b[0].candidate_id
        == "CAND_SVR"
    )

    decision_b = decide_recommendation(
        ranked_candidates=ranked_b,
        champion=rf_b,
        champion_source="PRODUCTION",
        metrics_by_candidate_department=(
            metric_map(
                "CAND_RF",
                "CAND_SVR",
            )
        ),
        policy=policy,
    )

    assert (
        decision_b.best_candidate_id
        == "CAND_SVR"
    )

    assert decision_b.action == "PROMOTE"

    assert decision_b.guardrail_pass

    assert (
        decision_b.improvement_pct
        > 1.0
    )

    assert (
        decision_b.recommended_candidate_id
        == "CAND_SVR"
    )

    # Acceptance point:
    # cùng candidate ids + cùng policy,
    # chỉ đổi metrics nhưng Recommendation phải đổi.
    assert (
        decision_a.recommended_candidate_id
        != decision_b.recommended_candidate_id
    )
