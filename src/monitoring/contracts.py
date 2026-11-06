from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MatchValues:
    actual_occupied_beds: int
    prediction_raw: float
    prediction_rounded: int
    error_raw: float
    abs_error_raw: float
    error_rounded: int
    abs_error_rounded: int
    underpredicted: bool
    overpredicted: bool
    exact_rounded: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CapacityEventMetrics:
    sample_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float | None
    recall: float | None
    accuracy: float

    def as_dict(self) -> dict:
        return asdict(self)