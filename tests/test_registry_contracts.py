import pytest

from src.registry.contracts import (
    ModelArtifactSpec,
)


def test_tabular_artifact_contract_is_valid():
    spec = ModelArtifactSpec(
        candidate_id="C1",
        run_id="R1",
        horizon=1,
        model_family="RF",
        artifact_path=(
            "models/c1.joblib"
        ),
        artifact_type=(
            "SKLEARN_JOBLIB"
        ),
        inference_type=(
            "TABULAR_28"
        ),
        feature_version="v2.0",
    )

    spec.validate()


def test_incompatible_artifact_and_inference_is_rejected():
    spec = ModelArtifactSpec(
        candidate_id="C2",
        run_id="R1",
        horizon=3,
        model_family="LSTM",
        artifact_path=(
            "models/lstm"
        ),
        artifact_type=(
            "SKLEARN_JOBLIB"
        ),
        inference_type=(
            "SEQUENCE_3X12"
        ),
        feature_version="v2.0",
    )

    with pytest.raises(
        ValueError
    ):
        spec.validate()