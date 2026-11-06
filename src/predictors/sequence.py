from __future__ import annotations

import json

from collections.abc import (
    Callable,
    Sequence,
)

from pathlib import Path

import numpy as np

from src.predictors.base import (
    PredictionResult,
)

from src.predictors.integrity import (
    verify_artifact_sha256,
)

from src.registry.contracts import (
    ModelArtifactSpec,
)


RAW_SEQUENCE_FEATURES = (
    "department_id",
    "planned_beds",
    "occupied_beds",
    "admissions",
    "discharges",
    "transfer_in",
    "transfer_out",
    "net_flow",
    "is_weekend",
    "dow_sin",
    "dow_cos",
)


class KerasSequencePredictorAdapter:
    """Adapter for the V2 LSTM bundle.

    Expected artifact directory:
        model.keras
        x_scaler.joblib
        y_scaler.joblib
        metadata.json
    """

    def __init__(
        self,
        spec: ModelArtifactSpec,
        model_loader: (
            Callable[[Path], object]
            | None
        ) = None,
        joblib_loader: (
            Callable[[Path], object]
            | None
        ) = None,
    ):
        spec.validate()

        if (
            spec.inference_type
            != "SEQUENCE_3X12"
        ):
            raise ValueError(
                "Sequence adapter requires "
                "inference_type=SEQUENCE_3X12"
            )

        self.spec = spec

        self._model_loader = (
            model_loader
            or self._default_model_loader
        )

        self._joblib_loader = (
            joblib_loader
            or self._default_joblib_loader
        )

        self._bundle = None

    @staticmethod
    def _default_model_loader(
        path: Path,
    ):
        try:
            from tensorflow.keras.models import (
                load_model,
            )

        except ImportError as exc:
            raise RuntimeError(
                "TensorFlow is required "
                "to load KERAS_BUNDLE "
                "artifacts. TensorFlow "
                "will be added with LSTM "
                "training in V2-14."
            ) from exc

        return load_model(
            path
        )

    @staticmethod
    def _default_joblib_loader(
        path: Path,
    ):
        try:
            import joblib

        except ImportError as exc:
            raise RuntimeError(
                "joblib is required "
                "for LSTM scaler artifacts"
            ) from exc

        return joblib.load(
            path
        )

    def _load_bundle(self):
        if self._bundle is not None:
            return self._bundle

        root = self.spec.path

        if not root.is_dir():
            raise FileNotFoundError(
                "LSTM artifact directory "
                f"not found: {root}"
            )

        verify_artifact_sha256(
            root,
            self.spec.artifact_sha256,
        )

        model_path = (
            root / "model.keras"
        )

        x_scaler_path = (
            root / "x_scaler.joblib"
        )

        y_scaler_path = (
            root / "y_scaler.joblib"
        )

        metadata_path = (
            root / "metadata.json"
        )

        for path in (
            model_path,
            x_scaler_path,
            y_scaler_path,
            metadata_path,
        ):
            if not path.exists():
                raise FileNotFoundError(
                    "Missing LSTM "
                    f"bundle file: {path}"
                )

        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

        categories = tuple(
            int(value)
            for value
            in metadata.get(
                "department_categories",
                [],
            )
        )

        if not categories:
            raise ValueError(
                "metadata.json must "
                "define "
                "department_categories"
            )

        self._bundle = {
            "model": (
                self._model_loader(
                    model_path
                )
            ),
            "x_scaler": (
                self._joblib_loader(
                    x_scaler_path
                )
            ),
            "y_scaler": (
                self._joblib_loader(
                    y_scaler_path
                )
            ),
            "department_categories": (
                categories
            ),
        }

        return self._bundle

    @staticmethod
    def _encode_row(
        row: dict,
        categories: tuple[int, ...],
    ) -> list[float]:
        missing = [
            name
            for name
            in RAW_SEQUENCE_FEATURES
            if name not in row
        ]

        if missing:
            raise ValueError(
                "Missing sequence "
                f"features: {missing}"
            )

        department_id = int(
            row["department_id"]
        )

        if (
            department_id
            not in categories
        ):
            raise ValueError(
                "department_id="
                f"{department_id} "
                "was not present in "
                "training categories "
                f"{categories}"
            )

        numeric = [
            float(
                row["planned_beds"]
            ),
            float(
                row["occupied_beds"]
            ),
            float(
                row["admissions"]
            ),
            float(
                row["discharges"]
            ),
            float(
                row["transfer_in"]
            ),
            float(
                row["transfer_out"]
            ),
            float(
                row["net_flow"]
            ),
            float(
                bool(
                    row["is_weekend"]
                )
            ),
            float(
                row["dow_sin"]
            ),
            float(
                row["dow_cos"]
            ),
        ]

        one_hot = [
            (
                1.0
                if department_id
                == category
                else 0.0
            )
            for category
            in categories
        ]

        return (
            numeric
            + one_hot
        )

    def predict_sequence(
        self,
        sequence_rows: Sequence[dict],
    ) -> PredictionResult:
        if len(sequence_rows) != 3:
            raise ValueError(
                "SEQUENCE_3X12 "
                "requires exactly "
                "3 timesteps; got "
                f"{len(sequence_rows)}"
            )

        bundle = (
            self._load_bundle()
        )

        categories = bundle[
            "department_categories"
        ]

        matrix = np.asarray(
            [
                self._encode_row(
                    row,
                    categories,
                )
                for row
                in sequence_rows
            ],
            dtype=float,
        )

        expected_width = (
            10
            + len(categories)
        )

        if matrix.shape != (
            3,
            expected_width,
        ):
            raise ValueError(
                "SEQUENCE_3X12 "
                "encoded shape must "
                f"be (3, {expected_width}); got "
                f"{matrix.shape}"
            )

        scaled = bundle[
            "x_scaler"
        ].transform(
            matrix
        )

        x = scaled.reshape(
            1,
            3,
            expected_width,
        )

        y_scaled = np.asarray(
            bundle["model"].predict(
                x,
                verbose=0,
            )
        ).reshape(
            -1,
            1,
        )

        y = bundle[
            "y_scaler"
        ].inverse_transform(
            y_scaled
        )

        raw = float(
            y[0, 0]
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

    def predict_tabular(
        self,
        feature_row: dict,
    ):
        raise TypeError(
            "SEQUENCE_3X12 adapter "
            "does not accept "
            "one-row tabular input"
        )