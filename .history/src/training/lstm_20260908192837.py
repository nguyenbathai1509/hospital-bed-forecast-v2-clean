from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import ParameterGrid

from src.predictors.integrity import artifact_sha256
from src.training.config import (
    LSTM_BATCH_SIZE,
    LSTM_DENSE_UNITS,
    LSTM_EARLY_STOPPING_PATIENCE,
    LSTM_GRID,
    LSTM_MAX_EPOCHS,
    SPLIT_SPEC,
    TemporalSplitSpec,
)
from src.training.data import SEQUENCE_BASE_NUMERIC_COLUMNS, split_by_target_date
from src.training.metrics import compute_metrics_by_department, compute_regression_metrics


@dataclass(frozen=True)
class LstmTrainingResult:
    model_family: str
    horizon: int
    best_params: dict[str, Any]
    validation_mae: float
    best_epoch: int
    overall_metrics: dict
    department_metrics: dict[int, dict]
    artifact_path: str
    artifact_sha256: str
    evaluation_fit_rows: int
    artifact_refit_rows: int
    department_categories: tuple[int, ...]


def _require_tensorflow():
    try:
        import tensorflow as tf
        return tf
    except ImportError as exc:
        raise RuntimeError(
            "TensorFlow is required for LSTM training. "
            "Install requirements-ml-lstm.txt first."
        ) from exc


def _set_seed(tf, seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    tf.keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass


def _build_model(tf, units: int, dropout: float, seed: int):
    _set_seed(tf, seed)
    tf.keras.backend.clear_session()
    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(3, 12)),
            tf.keras.layers.LSTM(units),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(LSTM_DENSE_UNITS, activation="relu"),
            tf.keras.layers.Dense(1),
        ]
    )
    model.compile(
        optimizer="adam",
        loss="mae",
        metrics=["mae"],
    )
    return model


def _stack_sequences(frame: pd.DataFrame):
    X = np.stack(frame["sequence"].to_list()).astype(float)
    y = frame["target_occupied_beds"].astype(float).to_numpy().reshape(-1, 1)
    return X, y


def _fit_scalers(X: np.ndarray, y: np.ndarray):
    x_scaler = StandardScaler()
    y_scaler = StandardScaler()
    x_scaler.fit(X.reshape(-1, X.shape[-1]))
    y_scaler.fit(y)
    return x_scaler, y_scaler


def _transform_x(scaler, X: np.ndarray) -> np.ndarray:
    shape = X.shape
    return scaler.transform(X.reshape(-1, shape[-1])).reshape(shape)


def _predict_original(model, x_scaler, y_scaler, X: np.ndarray) -> np.ndarray:
    X_scaled = _transform_x(x_scaler, X)
    y_scaled = np.asarray(model.predict(X_scaled, verbose=0)).reshape(-1, 1)
    return y_scaler.inverse_transform(y_scaled).reshape(-1)



def replay_lstm_evaluation(
    *,
    sequence_frame: pd.DataFrame,
    best_params: dict[str, Any],
    best_epoch: int,
    random_seed: int,
    split_spec: TemporalSplitSpec = SPLIT_SPEC,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Recreate only the historical LSTM holdout evaluation model.

    Scalers are fit on Train + Validation, then the evaluation model is trained
    for the stored best_epoch and predicts TEST. The refit Production bundle is
    never used for evaluation replay.
    """
    tf = _require_tensorflow()
    if int(best_epoch) <= 0:
        raise ValueError("best_epoch must be positive")

    partitions = split_by_target_date(sequence_frame, split_spec)
    X_dev, y_dev = _stack_sequences(partitions.development)
    X_test, _ = _stack_sequences(partitions.test)

    x_scaler, y_scaler = _fit_scalers(X_dev, y_dev)
    model = _build_model(
        tf,
        units=int(best_params["units"]),
        dropout=float(best_params["dropout"]),
        seed=random_seed,
    )
    model.fit(
        _transform_x(x_scaler, X_dev),
        y_scaler.transform(y_dev),
        epochs=int(best_epoch),
        batch_size=LSTM_BATCH_SIZE,
        shuffle=False,
        verbose=0,
    )
    predictions = _predict_original(model, x_scaler, y_scaler, X_test)

    return partitions.test.copy(), np.asarray(predictions, dtype=float)

def train_lstm_candidate(
    *,
    sequence_frame: pd.DataFrame,
    horizon: int,
    artifact_dir: Path,
    random_seed: int,
    department_categories: tuple[int, ...],
) -> LstmTrainingResult:
    tf = _require_tensorflow()

    if len(department_categories) != 2:
        raise ValueError(
            "V2 SEQUENCE_3X12 currently requires exactly 2 department categories; "
            f"got {department_categories}"
        )

    partitions = split_by_target_date(sequence_frame)
    X_train, y_train = _stack_sequences(partitions.train)
    X_val, y_val = _stack_sequences(partitions.validation)

    x_scaler, y_scaler = _fit_scalers(X_train, y_train)
    X_train_scaled = _transform_x(x_scaler, X_train)
    X_val_scaled = _transform_x(x_scaler, X_val)
    y_train_scaled = y_scaler.transform(y_train)

    tuned = []
    for params in ParameterGrid(LSTM_GRID):
        model = _build_model(
            tf,
            units=int(params["units"]),
            dropout=float(params["dropout"]),
            seed=random_seed,
        )
        callback = tf.keras.callbacks.EarlyStopping(
            monitor="val_mae",
            patience=LSTM_EARLY_STOPPING_PATIENCE,
            restore_best_weights=True,
        )
        history = model.fit(
            X_train_scaled,
            y_train_scaled,
            validation_data=(X_val_scaled, y_scaler.transform(y_val)),
            epochs=LSTM_MAX_EPOCHS,
            batch_size=LSTM_BATCH_SIZE,
            shuffle=False,
            verbose=0,
            callbacks=[callback],
        )
        val_pred = _predict_original(model, x_scaler, y_scaler, X_val)
        val_mae = compute_regression_metrics(y_val.reshape(-1), val_pred).mae
        val_history = history.history.get("val_mae", [])
        best_epoch = int(np.argmin(val_history) + 1) if val_history else len(history.epoch)
        tuned.append((val_mae, best_epoch, dict(params)))

    tuned.sort(key=lambda item: (item[0], item[1], repr(sorted(item[2].items()))))
    best_validation_mae, best_epoch, best_params = tuned[0]
    best_epoch = max(int(best_epoch), 1)

    development = partitions.development
    X_dev, y_dev = _stack_sequences(development)
    X_test, y_test = _stack_sequences(partitions.test)

    eval_x_scaler, eval_y_scaler = _fit_scalers(X_dev, y_dev)
    eval_model = _build_model(
        tf,
        units=int(best_params["units"]),
        dropout=float(best_params["dropout"]),
        seed=random_seed,
    )
    eval_model.fit(
        _transform_x(eval_x_scaler, X_dev),
        eval_y_scaler.transform(y_dev),
        epochs=best_epoch,
        batch_size=LSTM_BATCH_SIZE,
        shuffle=False,
        verbose=0,
    )
    test_pred = _predict_original(eval_model, eval_x_scaler, eval_y_scaler, X_test)
    y_test_flat = y_test.reshape(-1)

    overall = compute_regression_metrics(y_test_flat, test_pred).as_dict()
    per_department = {
        dep: metrics.as_dict()
        for dep, metrics in compute_metrics_by_department(
            partitions.test["department_id"].to_numpy(),
            y_test_flat,
            test_pred,
        ).items()
    }

    X_all, y_all = _stack_sequences(sequence_frame)
    prod_x_scaler, prod_y_scaler = _fit_scalers(X_all, y_all)
    prod_model = _build_model(
        tf,
        units=int(best_params["units"]),
        dropout=float(best_params["dropout"]),
        seed=random_seed,
    )
    prod_model.fit(
        _transform_x(prod_x_scaler, X_all),
        prod_y_scaler.transform(y_all),
        epochs=best_epoch,
        batch_size=LSTM_BATCH_SIZE,
        shuffle=False,
        verbose=0,
    )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    prod_model.save(artifact_dir / "model.keras")
    joblib.dump(prod_x_scaler, artifact_dir / "x_scaler.joblib")
    joblib.dump(prod_y_scaler, artifact_dir / "y_scaler.joblib")

    metadata = {
        "inference_type": "SEQUENCE_3X12",
        "sequence_length": 3,
        "base_numeric_features": list(SEQUENCE_BASE_NUMERIC_COLUMNS),
        "department_categories": list(department_categories),
        "encoded_width": 12,
        "best_epoch": best_epoch,
        "best_params": best_params,
        "batch_size": LSTM_BATCH_SIZE,
        "random_seed": random_seed,
    }
    (artifact_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    digest = artifact_sha256(artifact_dir)

    return LstmTrainingResult(
        model_family="LSTM",
        horizon=horizon,
        best_params=best_params,
        validation_mae=float(best_validation_mae),
        best_epoch=best_epoch,
        overall_metrics=overall,
        department_metrics=per_department,
        artifact_path=artifact_dir.as_posix(),
        artifact_sha256=digest,
        evaluation_fit_rows=len(development),
        artifact_refit_rows=len(sequence_frame),
        department_categories=department_categories,
    )