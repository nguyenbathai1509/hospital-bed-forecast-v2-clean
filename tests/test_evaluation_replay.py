from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.evaluation.service import (
    MAE_ABS_TOLERANCE,
    _prediction_rows,
    temporal_split_from_stored,
    validate_candidate_matrix,
)
from src.features.builder import FEATURE_VALUE_COLUMNS
from src.training.config import TemporalSplitSpec
from src.training.tabular import replay_tabular_evaluation


def _stored_split():
    return {
        "train_end": "2026-04-26",
        "validation_start": "2026-04-27",
        "validation_end": "2026-05-24",
        "test_start": "2026-05-25",
        "test_end": "2026-06-30",
        "split_axis": "target_date",
        "shuffle": "false",
    }


def test_temporal_split_from_stored_preserves_training_run_contract():
    spec = temporal_split_from_stored(_stored_split())
    assert spec.train_end == date(2026, 4, 26)
    assert spec.validation_start == date(2026, 4, 27)
    assert spec.test_start == date(2026, 5, 25)
    assert spec.test_end == date(2026, 6, 30)


def test_temporal_split_from_stored_rejects_shuffle_true():
    value = _stored_split()
    value["shuffle"] = "true"
    with pytest.raises(ValueError, match="shuffle=false"):
        temporal_split_from_stored(value)


def test_candidate_matrix_requires_all_8_horizon_family_candidates():
    candidates = [
        {"horizon": horizon, "model_family": family}
        for horizon in (1, 3)
        for family in ("RF", "XGBOOST", "SVR", "LSTM")
    ]
    validate_candidate_matrix(candidates)

    with pytest.raises(RuntimeError, match="candidate matrix is incomplete"):
        validate_candidate_matrix(candidates[:-1])


def test_prediction_rows_define_residual_as_actual_minus_predicted():
    dates = pd.date_range("2026-05-25", periods=37, freq="D")
    records = []
    predictions = []
    for department_id in (343, 344):
        for i, target_date in enumerate(dates):
            actual = 50.0 + (i % 3)
            prediction = actual - 1.25
            records.append(
                {
                    "origin_date": target_date.date(),
                    "target_date": target_date.date(),
                    "department_id": department_id,
                    "target_occupied_beds": actual,
                }
            )
            predictions.append(prediction)

    test_frame = pd.DataFrame(records)
    candidate = {
        "candidate_id": "TRN_TEST_H1_RF",
        "horizon": 1,
        "model_family": "RF",
        "feature_version": "v2.0",
        "data_version": "data-test",
        "mae": 1.25,
    }

    rows, summary = _prediction_rows(
        test_frame=test_frame,
        predictions=np.asarray(predictions),
        candidate=candidate,
        run_id="TRN_TEST",
    )

    assert len(rows) == 74
    assert rows[0]["residual"] == pytest.approx(1.25)
    assert rows[0]["absolute_error"] == pytest.approx(1.25)
    assert summary.replay_mae == pytest.approx(1.25)
    assert summary.mae_delta <= MAE_ABS_TOLERANCE


def test_prediction_rows_reject_metric_mismatch_before_persistence():
    dates = pd.date_range("2026-05-25", periods=37, freq="D")
    records = []
    predictions = []
    for department_id in (343, 344):
        for target_date in dates:
            records.append(
                {
                    "origin_date": target_date.date(),
                    "target_date": target_date.date(),
                    "department_id": department_id,
                    "target_occupied_beds": 50.0,
                }
            )
            predictions.append(48.0)

    with pytest.raises(RuntimeError, match="does not reproduce Model Registry"):
        _prediction_rows(
            test_frame=pd.DataFrame(records),
            predictions=np.asarray(predictions),
            candidate={
                "candidate_id": "TRN_TEST_H1_RF",
                "horizon": 1,
                "model_family": "RF",
                "feature_version": "v2.0",
                "data_version": "data-test",
                "mae": 1.0,
            },
            run_id="TRN_TEST",
        )


def test_tabular_replay_fits_development_then_returns_test_predictions():
    spec = TemporalSplitSpec(
        train_end=date(2026, 1, 2),
        validation_start=date(2026, 1, 3),
        validation_end=date(2026, 1, 3),
        test_start=date(2026, 1, 4),
        test_end=date(2026, 1, 4),
    )

    rows = []
    for day, target in (
        (date(2026, 1, 1), 40.0),
        (date(2026, 1, 2), 41.0),
        (date(2026, 1, 3), 42.0),
        (date(2026, 1, 4), 43.0),
    ):
        row = {
            "origin_date": day,
            "target_date": day,
            "target_occupied_beds": target,
        }
        for name in FEATURE_VALUE_COLUMNS:
            if name == "department_id":
                row[name] = 343
            elif name == "is_weekend":
                row[name] = 0
            else:
                row[name] = float(target)
        rows.append(row)

    test_frame, predictions = replay_tabular_evaluation(
        frame=pd.DataFrame(rows),
        model_family="RF",
        best_params={
            "n_estimators": 5,
            "max_depth": 2,
            "min_samples_leaf": 1,
            "max_features": 1.0,
        },
        random_seed=42,
        split_spec=spec,
    )

    assert len(test_frame) == 1
    assert test_frame.iloc[0]["target_date"] == date(2026, 1, 4)
    assert predictions.shape == (1,)
    assert np.isfinite(predictions[0])