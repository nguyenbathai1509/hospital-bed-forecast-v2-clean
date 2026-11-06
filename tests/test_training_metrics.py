import math

from src.training.metrics import (
    compute_regression_metrics,
)


def test_training_metrics_residual_sign_and_underprediction():
    metrics = (
        compute_regression_metrics(
            [
                10,
                20,
                30,
            ],
            [
                8,
                22,
                30,
            ],
        )
    )

    assert math.isclose(
        metrics.mae,
        4 / 3,
    )

    assert math.isclose(
        metrics.bias,
        0.0,
    )

    assert math.isclose(
        metrics.underprediction_rate,
        1 / 3,
    )

    assert math.isclose(
        metrics.underprediction_mae,
        2.0,
    )

    assert math.isclose(
        metrics.within_2_rate,
        1.0,
    )