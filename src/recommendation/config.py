from __future__ import annotations

from dataclasses import asdict, dataclass


BOOTSTRAP_CHAMPION_FAMILY = {
    1: "RF",
    3: "SVR",
}


@dataclass(frozen=True)
class RecommendationPolicy:
    """Initial V2 governance policy.

    These are configurable thesis/product guardrails, not clinical safety
    thresholds. They are intentionally explicit and persisted with each
    recommendation so the decision can be reproduced later.
    """

    minimum_improvement_pct: float = 1.0

    backtest_folds: int = 3
    backtest_min_fold_days: int = 7
    backtest_audit_days: int = 7

    max_rmse_degradation_pct: float = 5.0
    max_wape_degradation_points: float = 0.5
    max_p90_degradation_beds: float = 1.0
    max_max_error_degradation_beds: float = 2.0
    max_within2_drop: float = 0.05

    max_per_department_mae_degradation_pct: float = 10.0
    max_abs_bias_degradation_beds: float = 0.5
    max_underprediction_rate_increase: float = 0.05
    max_underprediction_mae_increase_beds: float = 0.5

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_POLICY = RecommendationPolicy()
