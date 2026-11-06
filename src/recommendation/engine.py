from __future__ import annotations

from collections.abc import Iterable

from src.recommendation.config import RecommendationPolicy
from src.recommendation.contracts import (
    CandidateMetrics,
    DepartmentMetrics,
    GuardrailCheck,
    RecommendationDecision,
)


def rank_candidates(
    candidates: Iterable[CandidateMetrics],
) -> list[CandidateMetrics]:
    """Rank by V2 primary metric MAE.

    RMSE and WAPE are deterministic tie breakers only. Guardrails are applied
    after the best-MAE challenger has been identified, matching V2 MASTER.
    """

    rows = list(candidates)

    if not rows:
        raise ValueError("At least one candidate is required")

    horizons = {row.horizon for row in rows}

    if len(horizons) != 1:
        raise ValueError(
            "rank_candidates requires candidates from exactly one horizon"
        )

    return sorted(
        rows,
        key=lambda row: (
            row.mae,
            row.rmse,
            row.wape,
            row.model_family,
            row.candidate_id,
        ),
    )


def improvement_pct(
    champion_mae: float,
    candidate_mae: float,
) -> float:
    if champion_mae <= 0:
        raise ValueError("champion_mae must be > 0")

    return (
        (champion_mae - candidate_mae)
        / champion_mae
        * 100.0
    )


def _relative_degradation_pct(
    champion_value: float,
    candidate_value: float,
) -> float:
    if champion_value == 0:
        return 0.0 if candidate_value <= 0 else float("inf")

    return (
        (candidate_value - champion_value)
        / abs(champion_value)
        * 100.0
    )


def evaluate_guardrails(
    *,
    candidate: CandidateMetrics,
    champion: CandidateMetrics,
    candidate_by_department: dict[int, DepartmentMetrics],
    champion_by_department: dict[int, DepartmentMetrics],
    policy: RecommendationPolicy,
) -> tuple[GuardrailCheck, ...]:
    checks: list[GuardrailCheck] = []

    same_window = candidate.split_spec == champion.split_spec

    checks.append(
        GuardrailCheck(
            name="SAME_EVALUATION_WINDOW",
            passed=same_window,
            candidate_value=None,
            champion_value=None,
            limit=None,
            detail=(
                "Candidate and Champion must be compared on the same "
                "temporal evaluation window."
            ),
        )
    )

    rmse_deg = _relative_degradation_pct(
        champion.rmse,
        candidate.rmse,
    )

    checks.append(
        GuardrailCheck(
            name="RMSE_DEGRADATION",
            passed=(rmse_deg <= policy.max_rmse_degradation_pct),
            candidate_value=candidate.rmse,
            champion_value=champion.rmse,
            limit=policy.max_rmse_degradation_pct,
            detail=(
                f"relative degradation={rmse_deg:.4f}% <= "
                f"{policy.max_rmse_degradation_pct:.4f}%"
            ),
        )
    )

    wape_delta = candidate.wape - champion.wape

    checks.append(
        GuardrailCheck(
            name="WAPE_DEGRADATION",
            passed=(wape_delta <= policy.max_wape_degradation_points),
            candidate_value=candidate.wape,
            champion_value=champion.wape,
            limit=policy.max_wape_degradation_points,
            detail=(
                f"delta={wape_delta:.4f} percentage points <= "
                f"{policy.max_wape_degradation_points:.4f}"
            ),
        )
    )

    p90_delta = candidate.p90_abs_error - champion.p90_abs_error

    checks.append(
        GuardrailCheck(
            name="P90_ABS_ERROR_DEGRADATION",
            passed=(p90_delta <= policy.max_p90_degradation_beds),
            candidate_value=candidate.p90_abs_error,
            champion_value=champion.p90_abs_error,
            limit=policy.max_p90_degradation_beds,
            detail=(
                f"delta={p90_delta:.4f} beds <= "
                f"{policy.max_p90_degradation_beds:.4f}"
            ),
        )
    )

    max_error_delta = candidate.max_abs_error - champion.max_abs_error

    checks.append(
        GuardrailCheck(
            name="MAX_ERROR_DEGRADATION",
            passed=(max_error_delta <= policy.max_max_error_degradation_beds),
            candidate_value=candidate.max_abs_error,
            champion_value=champion.max_abs_error,
            limit=policy.max_max_error_degradation_beds,
            detail=(
                f"delta={max_error_delta:.4f} beds <= "
                f"{policy.max_max_error_degradation_beds:.4f}"
            ),
        )
    )

    within2_drop = champion.within_2_rate - candidate.within_2_rate

    checks.append(
        GuardrailCheck(
            name="WITHIN_2_DROP",
            passed=(within2_drop <= policy.max_within2_drop),
            candidate_value=candidate.within_2_rate,
            champion_value=champion.within_2_rate,
            limit=policy.max_within2_drop,
            detail=(
                f"drop={within2_drop:.4f} <= "
                f"{policy.max_within2_drop:.4f}"
            ),
        )
    )

    bias_degradation = abs(candidate.bias) - abs(champion.bias)

    checks.append(
        GuardrailCheck(
            name="ABS_BIAS_DEGRADATION",
            passed=(
                bias_degradation
                <= policy.max_abs_bias_degradation_beds
            ),
            candidate_value=abs(candidate.bias),
            champion_value=abs(champion.bias),
            limit=policy.max_abs_bias_degradation_beds,
            detail=(
                f"|bias| delta={bias_degradation:.4f} beds <= "
                f"{policy.max_abs_bias_degradation_beds:.4f}"
            ),
        )
    )

    under_rate_delta = (
        candidate.underprediction_rate
        - champion.underprediction_rate
    )

    checks.append(
        GuardrailCheck(
            name="UNDERPREDICTION_RATE_INCREASE",
            passed=(
                under_rate_delta
                <= policy.max_underprediction_rate_increase
            ),
            candidate_value=candidate.underprediction_rate,
            champion_value=champion.underprediction_rate,
            limit=policy.max_underprediction_rate_increase,
            detail=(
                f"increase={under_rate_delta:.4f} <= "
                f"{policy.max_underprediction_rate_increase:.4f}"
            ),
        )
    )

    under_mae_delta = (
        candidate.underprediction_mae
        - champion.underprediction_mae
    )

    checks.append(
        GuardrailCheck(
            name="UNDERPREDICTION_MAE_INCREASE",
            passed=(
                under_mae_delta
                <= policy.max_underprediction_mae_increase_beds
            ),
            candidate_value=candidate.underprediction_mae,
            champion_value=champion.underprediction_mae,
            limit=policy.max_underprediction_mae_increase_beds,
            detail=(
                f"increase={under_mae_delta:.4f} beds <= "
                f"{policy.max_underprediction_mae_increase_beds:.4f}"
            ),
        )
    )

    candidate_departments = set(candidate_by_department)
    champion_departments = set(champion_by_department)
    same_departments = candidate_departments == champion_departments

    checks.append(
        GuardrailCheck(
            name="SAME_DEPARTMENT_COVERAGE",
            passed=same_departments,
            candidate_value=float(len(candidate_departments)),
            champion_value=float(len(champion_departments)),
            limit=None,
            detail=(
                f"candidate={sorted(candidate_departments)}, "
                f"champion={sorted(champion_departments)}"
            ),
        )
    )

    if same_departments:
        for department_id in sorted(candidate_departments):
            candidate_metric = candidate_by_department[department_id]
            champion_metric = champion_by_department[department_id]

            mae_deg = _relative_degradation_pct(
                champion_metric.mae,
                candidate_metric.mae,
            )

            checks.append(
                GuardrailCheck(
                    name=f"DEPARTMENT_{department_id}_MAE_DEGRADATION",
                    passed=(
                        mae_deg
                        <= policy.max_per_department_mae_degradation_pct
                    ),
                    candidate_value=candidate_metric.mae,
                    champion_value=champion_metric.mae,
                    limit=policy.max_per_department_mae_degradation_pct,
                    detail=(
                        f"relative degradation={mae_deg:.4f}% <= "
                        f"{policy.max_per_department_mae_degradation_pct:.4f}%"
                    ),
                )
            )

            dept_bias_deg = (
                abs(candidate_metric.bias)
                - abs(champion_metric.bias)
            )

            checks.append(
                GuardrailCheck(
                    name=f"DEPARTMENT_{department_id}_ABS_BIAS_DEGRADATION",
                    passed=(
                        dept_bias_deg
                        <= policy.max_abs_bias_degradation_beds
                    ),
                    candidate_value=abs(candidate_metric.bias),
                    champion_value=abs(champion_metric.bias),
                    limit=policy.max_abs_bias_degradation_beds,
                    detail=(
                        f"|bias| delta={dept_bias_deg:.4f} beds <= "
                        f"{policy.max_abs_bias_degradation_beds:.4f}"
                    ),
                )
            )

            dept_under_rate_delta = (
                candidate_metric.underprediction_rate
                - champion_metric.underprediction_rate
            )

            checks.append(
                GuardrailCheck(
                    name=(
                        f"DEPARTMENT_{department_id}_"
                        "UNDERPREDICTION_RATE_INCREASE"
                    ),
                    passed=(
                        dept_under_rate_delta
                        <= policy.max_underprediction_rate_increase
                    ),
                    candidate_value=(
                        candidate_metric.underprediction_rate
                    ),
                    champion_value=(
                        champion_metric.underprediction_rate
                    ),
                    limit=policy.max_underprediction_rate_increase,
                    detail=(
                        f"increase={dept_under_rate_delta:.4f} <= "
                        f"{policy.max_underprediction_rate_increase:.4f}"
                    ),
                )
            )

            dept_under_mae_delta = (
                candidate_metric.underprediction_mae
                - champion_metric.underprediction_mae
            )

            checks.append(
                GuardrailCheck(
                    name=(
                        f"DEPARTMENT_{department_id}_"
                        "UNDERPREDICTION_MAE_INCREASE"
                    ),
                    passed=(
                        dept_under_mae_delta
                        <= policy.max_underprediction_mae_increase_beds
                    ),
                    candidate_value=(
                        candidate_metric.underprediction_mae
                    ),
                    champion_value=(
                        champion_metric.underprediction_mae
                    ),
                    limit=policy.max_underprediction_mae_increase_beds,
                    detail=(
                        f"increase={dept_under_mae_delta:.4f} beds <= "
                        f"{policy.max_underprediction_mae_increase_beds:.4f}"
                    ),
                )
            )

    return tuple(checks)


def decide_recommendation(
    *,
    ranked_candidates: list[CandidateMetrics],
    champion: CandidateMetrics,
    champion_source: str,
    metrics_by_candidate_department: dict[
        str,
        dict[int, DepartmentMetrics],
    ],
    policy: RecommendationPolicy,
) -> RecommendationDecision:
    if not ranked_candidates:
        raise ValueError("ranked_candidates cannot be empty")

    best = ranked_candidates[0]

    if best.horizon != champion.horizon:
        raise ValueError(
            "Best candidate and Champion horizon mismatch"
        )

    if best.candidate_id == champion.candidate_id:
        return RecommendationDecision(
            horizon=best.horizon,
            best_candidate_id=best.candidate_id,
            champion_candidate_id=champion.candidate_id,
            recommended_candidate_id=champion.candidate_id,
            champion_source=champion_source,
            action="KEEP",
            improvement_pct=0.0,
            minimum_improvement_pct=policy.minimum_improvement_pct,
            guardrail_pass=True,
            reason_code="BEST_IS_CHAMPION",
            reasons=(
                "The Champion is already the lowest-MAE candidate on the "
                "current evaluation window.",
            ),
            guardrails=(),
        )

    if champion.mae == 0:
        guardrails = evaluate_guardrails(
            candidate=best, champion=champion,
            candidate_by_department=metrics_by_candidate_department.get(best.candidate_id, {}),
            champion_by_department=metrics_by_candidate_department.get(champion.candidate_id, {}),
            policy=policy,
        )
        return RecommendationDecision(
            horizon=best.horizon, best_candidate_id=best.candidate_id,
            champion_candidate_id=champion.candidate_id,
            recommended_candidate_id=champion.candidate_id, champion_source=champion_source,
            action="KEEP", improvement_pct=0.0,
            minimum_improvement_pct=policy.minimum_improvement_pct,
            guardrail_pass=all(check.passed for check in guardrails),
            reason_code="KEEP_CHAMPION_ZERO_ERROR",
            reasons=("Champion MAE is zero; relative improvement is undefined and no lower MAE is possible.",),
            guardrails=guardrails,
        )

    improvement = improvement_pct(
        champion.mae,
        best.mae,
    )

    guardrails = evaluate_guardrails(
        candidate=best,
        champion=champion,
        candidate_by_department=(
            metrics_by_candidate_department.get(
                best.candidate_id,
                {},
            )
        ),
        champion_by_department=(
            metrics_by_candidate_department.get(
                champion.candidate_id,
                {},
            )
        ),
        policy=policy,
    )

    guardrail_pass = all(
        check.passed
        for check in guardrails
    )

    improvement_pass = (
        improvement
        >= policy.minimum_improvement_pct
    )

    reasons: list[str] = []

    if not improvement_pass:
        reasons.append(
            "MAE improvement does not reach the configured minimum threshold."
        )

    failed_guardrails = [
        check.name
        for check in guardrails
        if not check.passed
    ]

    if failed_guardrails:
        reasons.append(
            "Guardrails failed: "
            + ", ".join(failed_guardrails)
        )

    if (
        improvement_pass
        and guardrail_pass
    ):
        action = "PROMOTE"
        recommended_candidate_id = (
            best.candidate_id
        )
        reason_code = (
            "PROMOTE_BEST_CANDIDATE"
        )

        reasons.append(
            "Best-MAE challenger clears minimum improvement "
            "and all guardrails."
        )

    else:
        action = "KEEP"
        recommended_candidate_id = (
            champion.candidate_id
        )

        if (
            not improvement_pass
            and not guardrail_pass
        ):
            reason_code = (
                "KEEP_THRESHOLD_AND_GUARDRAIL"
            )

        elif not improvement_pass:
            reason_code = (
                "KEEP_MINIMUM_IMPROVEMENT"
            )

        else:
            reason_code = (
                "KEEP_GUARDRAIL"
            )

    return RecommendationDecision(
        horizon=best.horizon,
        best_candidate_id=best.candidate_id,
        champion_candidate_id=champion.candidate_id,
        recommended_candidate_id=(
            recommended_candidate_id
        ),
        champion_source=champion_source,
        action=action,
        improvement_pct=float(
            improvement
        ),
        minimum_improvement_pct=(
            policy.minimum_improvement_pct
        ),
        guardrail_pass=guardrail_pass,
        reason_code=reason_code,
        reasons=tuple(reasons),
        guardrails=guardrails,
    )
