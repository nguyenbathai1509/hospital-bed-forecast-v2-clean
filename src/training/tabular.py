from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVR
from sklearn.model_selection import ParameterGrid

from src.predictors.integrity import artifact_sha256
from src.training.config import RF_GRID, SVR_GRID, XGBOOST_GRID, SPLIT_SPEC, TemporalSplitSpec
from src.training.data import (
    TABULAR_CATEGORICAL_COLUMNS,
    TABULAR_FEATURE_COLUMNS,
    TABULAR_NUMERIC_COLUMNS,
    split_by_target_date,
)
from src.training.metrics import compute_metrics_by_department, compute_regression_metrics


@dataclass(frozen=True)
class TabularTrainingResult:
    model_family: str
    horizon: int
    best_params: dict[str, Any]
    validation_mae: float
    overall_metrics: dict
    department_metrics: dict[int, dict]
    artifact_path: str
    artifact_sha256: str
    evaluation_fit_rows: int
    artifact_refit_rows: int


def _make_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    numeric_transformer = StandardScaler() if scale_numeric else "passthrough"
    return ColumnTransformer(
        transformers=[
            (
                "department",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                list(TABULAR_CATEGORICAL_COLUMNS),
            ),
            (
                "numeric",
                numeric_transformer,
                list(TABULAR_NUMERIC_COLUMNS),
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def _make_estimator(model_family: str, params: dict, random_seed: int):
    if model_family == "RF":
        return RandomForestRegressor(
            random_state=random_seed,
            n_jobs=1,
            **params,
        )

    if model_family == "SVR":
        return SVR(
            kernel="rbf",
            **params,
        )

    if model_family == "XGBOOST":
        try:
            from xgboost import XGBRegressor
        except ImportError as exc:
            raise RuntimeError(
                "XGBoost is required for V2-14. Install requirements.txt"
            ) from exc

        return XGBRegressor(
            objective="reg:squarederror",
            random_state=random_seed,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
            **params,
        )

    raise ValueError(f"Unsupported tabular model family: {model_family}")


def _make_pipeline(model_family: str, params: dict, random_seed: int) -> Pipeline:
    return Pipeline(
        steps=[
            (
                "preprocess",
                _make_preprocessor(scale_numeric=(model_family == "SVR")),
            ),
            (
                "model",
                _make_estimator(model_family, params, random_seed),
            ),
        ]
    )


def _grid_for(model_family: str) -> dict:
    if model_family == "RF":
        return RF_GRID
    if model_family == "XGBOOST":
        return XGBOOST_GRID
    if model_family == "SVR":
        return SVR_GRID
    raise ValueError(f"No grid for model family {model_family}")


def _xy(frame: pd.DataFrame):
    X = frame.loc[:, list(TABULAR_FEATURE_COLUMNS)].copy()
    y = frame["target_occupied_beds"].astype(float).to_numpy()
    return X, y



def replay_tabular_evaluation(
    *,
    frame: pd.DataFrame,
    model_family: str,
    best_params: dict[str, Any],
    random_seed: int,
    split_spec: TemporalSplitSpec = SPLIT_SPEC,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Recreate only the historical holdout evaluation model.

    This intentionally fits on Train + Validation and predicts TEST. It does not
    load or use the later ALL_MATURE Production artifact, so TEST remains a true
    holdout and no evaluation leakage is introduced.
    """
    if model_family not in {"RF", "XGBOOST", "SVR"}:
        raise ValueError("replay_tabular_evaluation only supports RF/XGBOOST/SVR")

    partitions = split_by_target_date(frame, split_spec)
    development = partitions.development
    X_dev, y_dev = _xy(development)
    X_test, _ = _xy(partitions.test)

    evaluation_model = _make_pipeline(
        model_family,
        dict(best_params),
        random_seed,
    )
    evaluation_model.fit(X_dev, y_dev)
    predictions = np.asarray(evaluation_model.predict(X_test), dtype=float)

    return partitions.test.copy(), predictions

def train_tabular_candidate(
    *,
    frame: pd.DataFrame,
    model_family: str,
    horizon: int,
    artifact_file: Path,
    random_seed: int,
    split_spec: TemporalSplitSpec | None = None,
) -> TabularTrainingResult:
    if model_family not in {"RF", "XGBOOST", "SVR"}:
        raise ValueError("train_tabular_candidate only supports RF/XGBOOST/SVR")

    if split_spec is None:
        split_spec = TemporalSplitSpec.ending_at(pd.to_datetime(frame["target_date"]).max().date())
    partitions = split_by_target_date(frame, split_spec)
    X_train, y_train = _xy(partitions.train)
    X_val, y_val = _xy(partitions.validation)

    candidates = []
    for params in ParameterGrid(_grid_for(model_family)):
        pipeline = _make_pipeline(model_family, params, random_seed)
        pipeline.fit(X_train, y_train)
        pred = np.asarray(pipeline.predict(X_val), dtype=float)
        mae = compute_regression_metrics(y_val, pred).mae
        candidates.append((mae, dict(params)))

    candidates.sort(key=lambda item: (item[0], repr(sorted(item[1].items()))))
    best_validation_mae, best_params = candidates[0]

    development = partitions.development
    X_dev, y_dev = _xy(development)
    X_test, y_test = _xy(partitions.test)

    evaluation_model = _make_pipeline(model_family, best_params, random_seed)
    evaluation_model.fit(X_dev, y_dev)
    test_pred = np.asarray(evaluation_model.predict(X_test), dtype=float)

    overall = compute_regression_metrics(y_test, test_pred).as_dict()
    per_department = {
        dep: metrics.as_dict()
        for dep, metrics in compute_metrics_by_department(
            partitions.test["department_id"].to_numpy(),
            y_test,
            test_pred,
        ).items()
    }

    X_all, y_all = _xy(frame)
    production_model = _make_pipeline(model_family, best_params, random_seed)
    production_model.fit(X_all, y_all)

    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(production_model, artifact_file)
    digest = artifact_sha256(artifact_file)

    return TabularTrainingResult(
        model_family=model_family,
        horizon=horizon,
        best_params=best_params,
        validation_mae=float(best_validation_mae),
        overall_metrics=overall,
        department_metrics=per_department,
        artifact_path=artifact_file.as_posix(),
        artifact_sha256=digest,
        evaluation_fit_rows=len(development),
        artifact_refit_rows=len(frame),
    )
