from pathlib import Path

import numpy as np

from src.features.builder import (
    FEATURE_VALUE_COLUMNS,
)

from src.predictors.factory import (
    create_predictor,
)

from src.predictors.sequence import (
    KerasSequencePredictorAdapter,
)

from src.predictors.tabular import (
    TabularSklearnPredictorAdapter,
)

from src.registry.contracts import (
    ModelArtifactSpec,
)


class FakeTabularModel:
    def predict(
        self,
        frame,
    ):
        assert (
            list(frame.columns)
            == FEATURE_VALUE_COLUMNS
        )

        return np.asarray(
            [42.25]
        )


def test_factory_builds_tabular_adapter_and_predicts(
    tmp_path: Path,
):
    artifact = (
        tmp_path
        / "model.joblib"
    )

    artifact.write_bytes(
        b"fake"
    )

    spec = ModelArtifactSpec(
        candidate_id="C_RF_H1",
        run_id="R1",
        horizon=1,
        model_family="RF",
        artifact_path=str(
            artifact
        ),
        artifact_type=(
            "SKLEARN_JOBLIB"
        ),
        inference_type=(
            "TABULAR_28"
        ),
        feature_version="v2.0",
        feature_order=tuple(
            FEATURE_VALUE_COLUMNS
        ),
    )

    adapter = create_predictor(
        spec,
        loader=lambda _: (
            FakeTabularModel()
        ),
    )

    assert isinstance(
        adapter,
        TabularSklearnPredictorAdapter,
    )

    row = {
        name: 1
        for name
        in FEATURE_VALUE_COLUMNS
    }

    result = (
        adapter.predict_tabular(
            row
        )
    )

    assert (
        result.prediction_raw
        == 42.25
    )

    assert (
        result.horizon
        == 1
    )

    assert (
        result.candidate_id
        == "C_RF_H1"
    )


def test_factory_builds_sequence_adapter_without_loading_tensorflow(
    tmp_path: Path,
):
    bundle = (
        tmp_path
        / "lstm_bundle"
    )

    bundle.mkdir()

    spec = ModelArtifactSpec(
        candidate_id="C_LSTM_H3",
        run_id="R1",
        horizon=3,
        model_family="LSTM",
        artifact_path=str(
            bundle
        ),
        artifact_type=(
            "KERAS_BUNDLE"
        ),
        inference_type=(
            "SEQUENCE_3X12"
        ),
        feature_version="v2.0",
    )

    adapter = create_predictor(
        spec
    )

    assert isinstance(
        adapter,
        KerasSequencePredictorAdapter,
    )