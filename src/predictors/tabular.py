from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from src.features.builder import (
    FEATURE_VALUE_COLUMNS,
)

from src.predictors.base import (
    PredictionResult,
)

from src.predictors.integrity import (
    verify_artifact_sha256,
)

from src.registry.contracts import (
    ModelArtifactSpec,
)


class TabularSklearnPredictorAdapter:
    def __init__(
        self,
        spec: ModelArtifactSpec,
        loader: (
            Callable[[Path], object]
            | None
        ) = None,
    ):
        spec.validate()

        if (
            spec.inference_type
            != "TABULAR_28"
        ):
            raise ValueError(
                "Tabular adapter requires "
                "inference_type=TABULAR_28"
            )

        self.spec = spec

        self._loader = (
            loader
            or self._default_loader
        )

        self._model = None

    @staticmethod
    def _default_loader(
        path: Path,
    ):
        try:
            import joblib

        except ImportError as exc:
            raise RuntimeError(
                "joblib is required to load "
                "SKLEARN_JOBLIB artifacts. "
                "It will be installed with "
                "the ML training dependencies "
                "in V2-14."
            ) from exc

        return joblib.load(
            path
        )

    def _load_model(self):
        if self._model is None:
            path = self.spec.path

            if not path.exists():
                raise FileNotFoundError(
                    "Model artifact "
                    f"not found: {path}"
                )

            verify_artifact_sha256(
                path,
                self.spec.artifact_sha256,
            )

            self._model = (
                self._loader(path)
            )

        return self._model

    def _feature_order(
        self,
    ) -> tuple[str, ...]:
        order = (
            self.spec.feature_order
            or tuple(
                FEATURE_VALUE_COLUMNS
            )
        )

        if len(order) != 28:
            raise ValueError(
                "TABULAR_28 requires "
                "exactly 28 features; "
                f"got {len(order)}"
            )

        return tuple(order)

    def predict_tabular(
        self,
        feature_row: dict,
    ) -> PredictionResult:
        order = self._feature_order()

        missing = [
            name
            for name in order
            if name
            not in feature_row
        ]

        if missing:
            raise ValueError(
                "Missing tabular "
                f"features: {missing}"
            )

        frame = pd.DataFrame(
            [
                {
                    name: (
                        feature_row[name]
                    )
                    for name in order
                }
            ],
            columns=list(order),
        )

        model = self._load_model()

        prediction = (
            model.predict(frame)
        )

        raw = float(
            prediction[0]
        )

        return PredictionResult(
            candidate_id=(
                self.spec.candidate_id
            ),
            horizon=(
                self.spec.horizon
            ),
            prediction_raw=raw,
            inference_type=(
                self.spec.inference_type
            ),
        )

    def predict_sequence(
        self,
        sequence_rows,
    ):
        raise TypeError(
            "TABULAR_28 adapter "
            "does not accept "
            "sequence input"
        )