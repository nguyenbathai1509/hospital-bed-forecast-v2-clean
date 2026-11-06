from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


PROMOTION_CONFIRMATION_PHRASE = "I_CONFIRM_PROMOTION"
ROLLBACK_CONFIRMATION_PHRASE = "I_CONFIRM_EMERGENCY_ROLLBACK"


@dataclass(frozen=True)
class ProductionCandidate:
    candidate_id: str
    horizon: int
    model_family: str
    mae: float
    run_id: str
    registry_status: str
    is_recommended: bool


@dataclass(frozen=True)
class PromotionPlanItem:
    horizon: int
    from_candidate_id: str | None
    from_model_family: str | None
    to_candidate_id: str
    to_model_family: str
    to_mae: float
    recommendation_id: str | None
    recommendation_action: str | None
    effect: str
    effective_from_business_date: date
    daily_lock_present: bool

    def as_dict(self) -> dict:
        result = asdict(self)
        result["effective_from_business_date"] = (
            self.effective_from_business_date.isoformat()
        )
        return result


@dataclass(frozen=True)
class PromotionPlan:
    business_date: date
    change_kind: str
    quota_used: bool
    items: tuple[PromotionPlanItem, ...]
    confirmation_phrase: str

    @property
    def has_changes(self) -> bool:
        return bool(self.items)

    def as_dict(self) -> dict:
        return {
            "business_date": self.business_date.isoformat(),
            "change_kind": self.change_kind,
            "quota_used": self.quota_used,
            "has_changes": self.has_changes,
            "confirmation_phrase": self.confirmation_phrase,
            "items": [item.as_dict() for item in self.items],
        }