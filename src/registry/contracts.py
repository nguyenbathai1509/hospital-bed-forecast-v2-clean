from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_MODEL_FAMILIES = {
    "RF",
    "XGBOOST",
    "SVR",
    "LSTM",
}

VALID_ARTIFACT_TYPES = {
    "SKLEARN_JOBLIB",
    "KERAS_BUNDLE",
}

VALID_INFERENCE_TYPES = {
    "TABULAR_28",
    "SEQUENCE_3X12",
}


@dataclass(frozen=True)
class ModelArtifactSpec:
    candidate_id: str
    run_id: str
    horizon: int
    model_family: str

    artifact_path: str
    artifact_type: str
    inference_type: str

    feature_version: str

    data_version: str | None = None
    artifact_sha256: str | None = None

    feature_order: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def validate(self) -> None:
        if not self.candidate_id:
            raise ValueError(
                "candidate_id is required"
            )

        if self.horizon not in {1, 3}:
            raise ValueError(
                "horizon must be 1 or 3"
            )

        if (
            self.model_family
            not in VALID_MODEL_FAMILIES
        ):
            raise ValueError(
                "Unsupported model_family: "
                f"{self.model_family}"
            )

        if (
            self.artifact_type
            not in VALID_ARTIFACT_TYPES
        ):
            raise ValueError(
                "Unsupported artifact_type: "
                f"{self.artifact_type}"
            )

        if (
            self.inference_type
            not in VALID_INFERENCE_TYPES
        ):
            raise ValueError(
                "Unsupported inference_type: "
                f"{self.inference_type}"
            )

        if not self.feature_version:
            raise ValueError(
                "feature_version is required"
            )

        if not self.artifact_path:
            raise ValueError(
                "artifact_path is required"
            )

        if (
            self.inference_type
            == "TABULAR_28"
            and self.artifact_type
            != "SKLEARN_JOBLIB"
        ):
            raise ValueError(
                "TABULAR_28 requires "
                "SKLEARN_JOBLIB artifact_type"
            )

        if (
            self.inference_type
            == "SEQUENCE_3X12"
            and self.artifact_type
            != "KERAS_BUNDLE"
        ):
            raise ValueError(
                "SEQUENCE_3X12 requires "
                "KERAS_BUNDLE artifact_type"
            )

    @property
    def path(self) -> Path:
        return Path(
            self.artifact_path
        )