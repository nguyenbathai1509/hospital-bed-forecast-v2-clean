from src.training.config import (
    EXPECTED_FAMILIES,
    EXPECTED_HORIZONS,
    LSTM_GRID,
    RF_GRID,
    SVR_GRID,
    XGBOOST_GRID,
)


def test_v2_training_grids_preserve_master_contract():
    assert (
        EXPECTED_HORIZONS
        == (1, 3)
    )

    assert (
        EXPECTED_FAMILIES
        == (
            "RF",
            "XGBOOST",
            "SVR",
            "LSTM",
        )
    )

    assert (
        RF_GRID[
            "n_estimators"
        ]
        == [200, 400]
    )

    assert (
        RF_GRID[
            "max_depth"
        ]
        == [
            3,
            5,
            None,
        ]
    )

    assert (
        SVR_GRID["C"]
        == [
            1,
            10,
            30,
        ]
    )

    assert (
        SVR_GRID[
            "epsilon"
        ]
        == [
            0.1,
            0.2,
            0.5,
        ]
    )

    assert (
        SVR_GRID[
            "gamma"
        ]
        == [
            "scale",
            0.01,
            0.1,
        ]
    )

    assert (
        XGBOOST_GRID[
            "max_depth"
        ]
        == [2, 3]
    )

    assert (
        XGBOOST_GRID[
            "learning_rate"
        ]
        == [
            0.03,
            0.05,
        ]
    )

    assert (
        LSTM_GRID
        == {
            "units": [
                16,
                32,
            ],
            "dropout": [
                0.0,
                0.2,
            ],
        }
    )