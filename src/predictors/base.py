from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from src.registry.contracts import (
    ModelArtifactSpec,
)


@dataclass(frozen=True)
class PredictionResult:
    candidate_id: str
    horizon: int
    prediction_raw: float
    inference_type: str


class PredictorAdapter(Protocol):
    spec: ModelArtifactSpec

    def predict_tabular(
        self,
        feature_row: dict,
    ) -> PredictionResult:
        ...

    def predict_sequence(
        self,
        sequence_rows: Sequence[dict],
    ) -> PredictionResult:
        ...