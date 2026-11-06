from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


OFFICIAL_CONFIRMATION_PHRASE = "I_CONFIRM_OFFICIAL"
VALID_PREVIEW_MODES = {"PRODUCTION", "RECOMMENDED", "CUSTOM"}


@dataclass(frozen=True)
class ForecastValue:
    prediction_raw: float
    prediction_rounded: int
    planned_beds: int
    predicted_utilization_pct: float
    capacity_alert: bool
    capacity_excess_beds: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ForecastPrediction:
    origin_date: date
    department_id: int
    horizon: int
    target_date: date
    candidate_id: str
    model_family: str
    source_mode: str
    feature_version: str
    data_version: str | None
    value: ForecastValue

    def as_dict(self) -> dict:
        return {
            "origin_date": self.origin_date.isoformat(),
            "department_id": self.department_id,
            "horizon": self.horizon,
            "target_date": self.target_date.isoformat(),
            "candidate_id": self.candidate_id,
            "model_family": self.model_family,
            "source_mode": self.source_mode,
            "feature_version": self.feature_version,
            "data_version": self.data_version,
            **self.value.as_dict(),
        }