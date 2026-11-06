from pathlib import Path

import numpy as np
import pytest

from src.predictors.sequence import (
    KerasSequencePredictorAdapter,
)
from src.registry.contracts import (
    ModelArtifactSpec,
)


class FakeXScaler:
    def __init__(self):
        self.last_shape = None

    def transform(
        self,
        matrix,
    ):
        matrix = np.asarray(
            matrix,
            dtype=float,
        )

        self.last_shape = (
            matrix.shape
        )

        return matrix


class FakeYScaler:
    def inverse_transform(
        self,
        values,
    ):
        return np.asarray(
            values,
            dtype=float,
        )


class FakeModel:
    def __init__(self):
        self.called = False
        self.last_shape = None

    def predict(
        self,
        x,
        verbose=0,
    ):
        self.called = True
        self.last_shape = (
            np.asarray(x).shape
        )

        return np.asarray(
            [[42.25]],
            dtype=float,
        )


def row(
    department_id,
):
    return {
        "department_id":
            department_id,
        "planned_beds": 55,
        "occupied_beds": 48,
        "admissions": 5,
        "discharges": 4,
        "transfer_in": 1,
        "transfer_out": 0,
        "net_flow": 2,
        "is_weekend": False,
        "dow_sin": 0.5,
        "dow_cos": 0.5,
    }


def build_adapter(
    tmp_path: Path,
    categories,
):
    bundle = (
        tmp_path
        / (
            "bundle_"
            + "_".join(
                str(value)
                for value
                in categories
            )
        )
    )

    bundle.mkdir()

    spec = ModelArtifactSpec(
        candidate_id="C_LSTM_DYNAMIC",
        run_id="TRN_DYNAMIC",
        horizon=1,
        model_family="LSTM",
        artifact_path=str(
            bundle
        ),
        artifact_type="KERAS_BUNDLE",
        inference_type="SEQUENCE_3X12",
        feature_version="v2.0",
    )

    adapter = (
        KerasSequencePredictorAdapter(
            spec
        )
    )

    x_scaler = FakeXScaler()
    y_scaler = FakeYScaler()
    model = FakeModel()

    adapter._bundle = {
        "model": model,
        "x_scaler": x_scaler,
        "y_scaler": y_scaler,
        "department_categories":
            tuple(categories),
    }

    return (
        adapter,
        x_scaler,
        model,
    )


@pytest.mark.parametrize(
    (
        "categories",
        "department_id",
        "expected_width",
    ),
    [
        (
            (343, 344),
            344,
            12,
        ),
        (
            (343, 344, 345),
            345,
            13,
        ),
        (
            (
                343,
                344,
                345,
                346,
                347,
            ),
            347,
            15,
        ),
    ],
)
def test_lstm_width_follows_number_of_training_departments(
    tmp_path,
    categories,
    department_id,
    expected_width,
):
    (
        adapter,
        x_scaler,
        model,
    ) = build_adapter(
        tmp_path,
        categories,
    )

    result = (
        adapter.predict_sequence(
            [
                row(
                    department_id
                ),
                row(
                    department_id
                ),
                row(
                    department_id
                ),
            ]
        )
    )

    assert (
        x_scaler.last_shape
        == (
            3,
            expected_width,
        )
    )

    assert (
        model.last_shape
        == (
            1,
            3,
            expected_width,
        )
    )

    assert (
        result.prediction_raw
        == 42.25
    )


def test_unknown_department_is_rejected_before_model_prediction(
    tmp_path,
):
    (
        adapter,
        _,
        model,
    ) = build_adapter(
        tmp_path,
        (
            343,
            344,
            345,
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "was not present in "
            "training categories"
        ),
    ):
        adapter.predict_sequence(
            [
                row(346),
                row(346),
                row(346),
            ]
        )

    assert model.called is False


def test_lstm_still_requires_exactly_three_timesteps(
    tmp_path,
):
    (
        adapter,
        _,
        model,
    ) = build_adapter(
        tmp_path,
        (
            343,
            344,
            345,
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "requires exactly "
            "3 timesteps"
        ),
    ):
        adapter.predict_sequence(
            [
                row(345),
                row(345),
            ]
        )

    assert model.called is False
