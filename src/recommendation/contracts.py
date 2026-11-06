from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateMetrics:
    candidate_id: str
    run_id: str
    horizon: int
    model_family: str

    mae: float
    rmse: float
    wape: float
    r2: float | None
    bias: float
    p90_abs_error: float
    max_abs_error: float
    within_2_rate: float
    underprediction_rate: float
    underprediction_mae: float

    split_spec: dict[str, Any]


@dataclass(frozen=True)
class DepartmentMetrics:
    candidate_id: str
    department_id: int
    sample_count: int
    mae: float
    rmse: float
    wape: float
    r2: float | None
    bias: float
    p90_abs_error: float
    max_abs_error: float
    within_2_rate: float
    underprediction_rate: float
    underprediction_mae: float


@dataclass(frozen=True)
class GuardrailCheck:
    name: str
    passed: bool
    candidate_value: float | None
    champion_value: float | None
    limit: float | None
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationDecision:
    horizon: int
    best_candidate_id: str
    champion_candidate_id: str
    recommended_candidate_id: str
    champion_source: str
    action: str
    improvement_pct: float
    minimum_improvement_pct: float
    guardrail_pass: bool
    reason_code: str
    reasons: tuple[str, ...]
    guardrails: tuple[GuardrailCheck, ...]

    def as_dict(self) -> dict:
        return {
            "horizon": self.horizon,
            "best_candidate_id": self.best_candidate_id,
            "champion_candidate_id": self.champion_candidate_id,
            "recommended_candidate_id": self.recommended_candidate_id,
            "champion_source": self.champion_source,
            "action": self.action,
            "improvement_pct": self.improvement_pct,
            "minimum_improvement_pct": self.minimum_improvement_pct,
            "guardrail_pass": self.guardrail_pass,
            "reason_code": self.reason_code,
            "reasons": list(self.reasons),
            "guardrails": [
                check.as_dict()
                for check in self.guardrails
            ],
        }