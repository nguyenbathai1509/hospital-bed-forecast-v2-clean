import json
from pathlib import Path

import pytest

from src.predictors.integrity import (
    artifact_sha256,
)
from src.predictors.sequence import (
    KerasSequencePredictorAdapter,
)
from src.registry.contracts import (
    ModelArtifactSpec,
)


def write_bundle(
    root: Path,
    categories=(343, 344, 345),
):
    root.mkdir()

    (
        root
        / "model.keras"
    ).write_bytes(
        b"fake-keras-model"
    )

    (
        root
        / "x_scaler.joblib"
    ).write_bytes(
        b"fake-x-scaler"
    )

    (
        root
        / "y_scaler.joblib"
    ).write_bytes(
        b"fake-y-scaler"
    )

    (
        root
        / "metadata.json"
    ).write_text(
        json.dumps(
            {
                "department_categories":
                    list(categories),
            }
        ),
        encoding="utf-8",
    )


def make_spec(
    root: Path,
    digest=None,
):
    return ModelArtifactSpec(
        candidate_id="C_LSTM_ARTIFACT",
        run_id="TRN_ARTIFACT",
        horizon=1,
        model_family="LSTM",
        artifact_path=str(root),
        artifact_type="KERAS_BUNDLE",
        inference_type="SEQUENCE_3X12",
        feature_version="v2.0",
        artifact_sha256=digest,
    )


def make_adapter(
    root: Path,
    digest=None,
):
    calls = {
        "model": 0,
        "joblib": 0,
    }

    def model_loader(
        path,
    ):
        calls["model"] += 1
        return {
            "loaded":
                path.name,
        }

    def joblib_loader(
        path,
    ):
        calls["joblib"] += 1
        return {
            "loaded":
                path.name,
        }

    adapter = (
        KerasSequencePredictorAdapter(
            make_spec(
                root,
                digest,
            ),
            model_loader=model_loader,
            joblib_loader=joblib_loader,
        )
    )

    return adapter, calls


def test_valid_lstm_bundle_with_correct_sha256_loads(
    tmp_path,
):
    root = (
        tmp_path
        / "valid_bundle"
    )

    write_bundle(root)

    digest = (
        artifact_sha256(
            root
        )
    )

    adapter, calls = (
        make_adapter(
            root,
            digest,
        )
    )

    bundle = (
        adapter._load_bundle()
    )

    assert (
        bundle[
            "department_categories"
        ]
        == (
            343,
            344,
            345,
        )
    )

    assert calls == {
        "model": 1,
        "joblib": 2,
    }


def test_tampered_lstm_bundle_is_rejected_before_loaders(
    tmp_path,
):
    root = (
        tmp_path
        / "tampered_bundle"
    )

    write_bundle(root)

    digest = (
        artifact_sha256(
            root
        )
    )

    (
        root
        / "model.keras"
    ).write_bytes(
        b"tampered-model"
    )

    adapter, calls = (
        make_adapter(
            root,
            digest,
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "Artifact SHA-256 mismatch"
        ),
    ):
        adapter._load_bundle()

    assert calls == {
        "model": 0,
        "joblib": 0,
    }


def test_missing_required_lstm_bundle_file_is_rejected_before_loaders(
    tmp_path,
):
    root = (
        tmp_path
        / "missing_file_bundle"
    )

    write_bundle(root)

    (
        root
        / "y_scaler.joblib"
    ).unlink()

    adapter, calls = (
        make_adapter(
            root
        )
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            "Missing LSTM bundle file"
        ),
    ):
        adapter._load_bundle()

    assert calls == {
        "model": 0,
        "joblib": 0,
    }


def test_empty_department_categories_are_rejected_before_loaders(
    tmp_path,
):
    root = (
        tmp_path
        / "invalid_metadata_bundle"
    )

    write_bundle(
        root,
        categories=(),
    )

    adapter, calls = (
        make_adapter(
            root
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "metadata.json must define "
            "department_categories"
        ),
    ):
        adapter._load_bundle()

    assert calls == {
        "model": 0,
        "joblib": 0,
    }


def test_non_directory_lstm_artifact_is_rejected(
    tmp_path,
):
    artifact = (
        tmp_path
        / "not_a_directory.keras"
    )

    artifact.write_bytes(
        b"not-a-bundle"
    )

    adapter, calls = (
        make_adapter(
            artifact
        )
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            "LSTM artifact directory "
            "not found"
        ),
    ):
        adapter._load_bundle()

    assert calls == {
        "model": 0,
        "joblib": 0,
    }
