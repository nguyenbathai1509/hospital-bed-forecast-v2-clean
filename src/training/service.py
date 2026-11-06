from __future__ import annotations

from src.training.job_context import fence_training_job, link_training_run

from datetime import (
    datetime,
    timezone,
)

import json
from pathlib import Path
import uuid

import pandas as pd

from src.config import settings

from src.db.engine import (
    create_sql_engine,
)

from src.features.builder import (
    FEATURE_VALUE_COLUMNS,
)

from src.training.config import (
    DEFAULT_RANDOM_SEED,
    EXPECTED_FAMILIES,
    EXPECTED_HORIZONS,
    LSTM_GRID,
    RF_GRID,
    TemporalSplitSpec,
    SVR_GRID,
    TRAINING_CONTRACT_VERSION,
    XGBOOST_GRID,
)

from src.training.data import (
    build_sequence_frame,
    feature_contract_hash,
    split_by_target_date,
)

from src.training.environment import (
    capture_code_revision,
    capture_environment,
)

from src.training.lstm import (
    train_lstm_candidate,
)

from src.training.repository import (
    TrainingRepository,
)

from src.training.tabular import (
    train_tabular_candidate,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

DEFAULT_ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "models"
    / "registry"
)


def _new_run_id() -> str:
    return (
        "TRN_"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


def _candidate_id(
    run_id: str,
    horizon: int,
    family: str,
) -> str:
    return (
        f"{run_id}_"
        f"H{horizon}_"
        f"{family}"
    )


def _relative_artifact_path(
    path: Path,
) -> str:
    try:
        return (
            path.resolve()
            .relative_to(
                PROJECT_ROOT.resolve()
            )
            .as_posix()
        )

    except ValueError:
        return (
            path.resolve()
            .as_posix()
        )


def _algorithm_set() -> dict:
    return {
        "families": list(
            EXPECTED_FAMILIES
        ),
        "RF_grid": (
            RF_GRID
        ),
        "XGBOOST_grid": (
            XGBOOST_GRID
        ),
        "SVR_grid": (
            SVR_GRID
        ),
        "LSTM_grid": (
            LSTM_GRID
        ),
        "ranking_metric": "MAE",
        "hyperparameter_selection_region": (
            "VALIDATION_ONLY"
        ),
        "final_holdout_used_for_tuning": (
            False
        ),
        "artifact_refit_policy": (
            "REFIT_ALL_MATURE_"
            "AFTER_HOLDOUT_EVALUATION"
        ),
    }


def run_training(
    *,
    triggered_by: str = "manual",
    random_seed: int = (
        DEFAULT_RANDOM_SEED
    ),
    artifact_root: Path = (
        DEFAULT_ARTIFACT_ROOT
    ),
) -> dict:
    engine = (
        create_sql_engine()
    )

    with engine.connect() as conn:
        repo = TrainingRepository(
            conn
        )

        ready = (
            repo.latest_data_ready_context()
        )

        if ready is None:
            raise RuntimeError(
                "No DATA_READY Daily Pipeline "
                "run exists"
            )

        business_date = (
            ready["business_date"]
        )

        data_version = (
            ready["data_version"]
        )

        existing = (
            repo.completed_run_for_business_date(
                business_date
            )
        )

    if existing is not None:
        return {
            "status": (
                "ALREADY_COMPLETED"
            ),
            "business_date": str(
                business_date
            ),
            "run_id": (
                existing["run_id"]
            ),
            "message": (
                "A COMPLETED Training Run "
                "already exists for this "
                "business_date."
            ),
        }

    datasets: dict[
        int,
        pd.DataFrame,
    ] = {}

    feature_history: list[
        dict
    ]

    sample_rows_by_horizon: dict[
        int,
        list[dict],
    ] = {}

    with engine.connect() as conn:
        repo = TrainingRepository(
            conn
        )

        for horizon in (
            EXPECTED_HORIZONS
        ):
            rows = (
                repo.fetch_tabular_dataset(
                    horizon,
                    settings.feature_version,
                )
            )

            if not rows:
                raise RuntimeError(
                    "No ML samples found "
                    f"for horizon H+{horizon}"
                )

            datasets[
                horizon
            ] = pd.DataFrame(
                rows
            )

            sample_rows_by_horizon[
                horizon
            ] = repo.fetch_ml_samples(
                horizon,
                settings.feature_version,
            )

        feature_history = (
            repo.fetch_feature_history(
                settings.feature_version
            )
        )

    all_frames = pd.concat(
        list(
            datasets.values()
        ),
        ignore_index=True,
    )

    data_start = (
        pd.to_datetime(
            all_frames[
                "origin_date"
            ]
        )
        .dt.date
        .min()
    )

    data_end = (
        pd.to_datetime(
            all_frames[
                "target_date"
            ]
        )
        .dt.date
        .max()
    )

    # Every horizon/family in the run uses the same calendar boundaries.
    # Validate before creating a run or writing any model artifacts.
    split_spec = TemporalSplitSpec.ending_at(data_end)
    for horizon, frame in datasets.items():
        try:
            split_by_target_date(frame, split_spec)
            split_by_target_date(pd.DataFrame(sample_rows_by_horizon[horizon]), split_spec)
        except ValueError as exc:
            raise ValueError(f"Cannot train H+{horizon}: {exc}") from exc

    department_count = int(
        all_frames[
            "department_id"
        ].nunique()
    )

    row_count = int(
        len(
            all_frames
        )
    )

    run_id = (
        _new_run_id()
    )

    run_artifact_dir = (
        artifact_root
        / run_id
    )

    environment = (
        capture_environment()
    )

    code_revision = (
        capture_code_revision(
            PROJECT_ROOT
        )
    )

    with engine.begin() as conn:
        fence_training_job(conn)
        TrainingRepository(
            conn
        ).create_training_run(
            run_id=run_id,
            business_date=business_date,
            triggered_by=triggered_by,
            data_start=data_start,
            data_end=data_end,
            data_version=data_version,
            feature_version=(
                settings.feature_version
            ),
            feature_hash=(
                feature_contract_hash(
                    settings.feature_version
                )
            ),
            row_count=row_count,
            department_count=(
                department_count
            ),
            split_spec=(
                split_spec.as_dict()
            ),
            algorithm_set=(
                _algorithm_set()
            ),
            code_revision=(
                code_revision
            ),
            random_seed=(
                random_seed
            ),
            environment=(
                environment
            ),
            training_contract_version=(
                TRAINING_CONTRACT_VERSION
            ),
        )

        link_training_run(conn, run_id)

    registered = 0
    summaries = []

    try:
        for horizon in (
            EXPECTED_HORIZONS
        ):
            frame = datasets[
                horizon
            ]

            for family in (
                "RF",
                "XGBOOST",
                "SVR",
            ):
                candidate_id = (
                    _candidate_id(
                        run_id,
                        horizon,
                        family,
                    )
                )

                artifact_file = (
                    run_artifact_dir
                    / (
                        f"{candidate_id}"
                        ".joblib"
                    )
                )

                result = (
                    train_tabular_candidate(
                        frame=frame,
                        split_spec=split_spec,
                        model_family=family,
                        horizon=horizon,
                        artifact_file=(
                            artifact_file
                        ),
                        random_seed=(
                            random_seed
                        ),
                    )
                )

                metadata = {
                    "validation_mae": (
                        result.validation_mae
                    ),
                    "evaluation_fit_rows": (
                        result.evaluation_fit_rows
                    ),
                    "artifact_refit_rows": (
                        result.artifact_refit_rows
                    ),
                    "artifact_refit_policy": (
                        "ALL_MATURE_"
                        "AFTER_EVALUATION"
                    ),
                    "random_seed": (
                        random_seed
                    ),
                    "split_spec": (
                        split_spec.as_dict()
                    ),
                    "environment": (
                        environment
                    ),
                    "code_revision": (
                        code_revision
                    ),
                    "training_contract_version": (
                        TRAINING_CONTRACT_VERSION
                    ),
                }

                stored_path = (
                    _relative_artifact_path(
                        Path(
                            result.artifact_path
                        )
                    )
                )

                with engine.begin() as conn:
                    fence_training_job(conn)
                    TrainingRepository(
                        conn
                    ).insert_candidate(
                        candidate_id=(
                            candidate_id
                        ),
                        run_id=run_id,
                        horizon=horizon,
                        model_family=family,
                        artifact_path=(
                            stored_path
                        ),
                        artifact_type=(
                            "SKLEARN_JOBLIB"
                        ),
                        inference_type=(
                            "TABULAR_28"
                        ),
                        artifact_sha256=(
                            result.artifact_sha256
                        ),
                        feature_version=(
                            settings.feature_version
                        ),
                        data_version=(
                            data_version
                        ),
                        feature_order=list(
                            FEATURE_VALUE_COLUMNS
                        ),
                        model_metadata=(
                            metadata
                        ),
                        best_params=(
                            result.best_params
                        ),
                        overall_metrics=(
                            result.overall_metrics
                        ),
                        department_metrics=(
                            result.department_metrics
                        ),
                    )

                registered += 1

                summaries.append(
                    {
                        "candidate_id": (
                            candidate_id
                        ),
                        "horizon": (
                            horizon
                        ),
                        "model_family": (
                            family
                        ),
                        "validation_mae": (
                            result.validation_mae
                        ),
                        "test_mae": (
                            result.overall_metrics[
                                "mae"
                            ]
                        ),
                        "artifact_path": (
                            stored_path
                        ),
                    }
                )

            categories = tuple(
                sorted(
                    {
                        int(
                            row[
                                "department_id"
                            ]
                        )
                        for row
                        in feature_history
                    }
                )
            )

            sequence_frame = (
                build_sequence_frame(
                    feature_rows=(
                        feature_history
                    ),
                    sample_rows=(
                        sample_rows_by_horizon[
                            horizon
                        ]
                    ),
                    department_categories=(
                        categories
                    ),
                )
            )

            candidate_id = (
                _candidate_id(
                    run_id,
                    horizon,
                    "LSTM",
                )
            )

            artifact_dir = (
                run_artifact_dir
                / candidate_id
            )

            result = (
                train_lstm_candidate(
                    split_spec=split_spec,
                    sequence_frame=(
                        sequence_frame
                    ),
                    horizon=horizon,
                    artifact_dir=(
                        artifact_dir
                    ),
                    random_seed=(
                        random_seed
                    ),
                    department_categories=(
                        categories
                    ),
                )
            )

            metadata = {
                "validation_mae": (
                    result.validation_mae
                ),
                "best_epoch": (
                    result.best_epoch
                ),
                "evaluation_fit_rows": (
                    result.evaluation_fit_rows
                ),
                "artifact_refit_rows": (
                    result.artifact_refit_rows
                ),
                "artifact_refit_policy": (
                    "ALL_MATURE_"
                    "AFTER_EVALUATION"
                ),
                "department_categories": list(
                    result.department_categories
                ),
                "random_seed": (
                    random_seed
                ),
                "split_spec": (
                    split_spec.as_dict()
                ),
                "environment": (
                    environment
                ),
                "code_revision": (
                    code_revision
                ),
                "training_contract_version": (
                    TRAINING_CONTRACT_VERSION
                ),
            }

            stored_path = (
                _relative_artifact_path(
                    Path(
                        result.artifact_path
                    )
                )
            )

            with engine.begin() as conn:
                fence_training_job(conn)
                TrainingRepository(
                    conn
                ).insert_candidate(
                    candidate_id=(
                        candidate_id
                    ),
                    run_id=run_id,
                    horizon=horizon,
                    model_family=(
                        "LSTM"
                    ),
                    artifact_path=(
                        stored_path
                    ),
                    artifact_type=(
                        "KERAS_BUNDLE"
                    ),
                    inference_type=(
                        "SEQUENCE_3X12"
                    ),
                    artifact_sha256=(
                        result.artifact_sha256
                    ),
                    feature_version=(
                        settings.feature_version
                    ),
                    data_version=(
                        data_version
                    ),
                    feature_order=[],
                    model_metadata=(
                        metadata
                    ),
                    best_params=(
                        result.best_params
                    ),
                    overall_metrics=(
                        result.overall_metrics
                    ),
                    department_metrics=(
                        result.department_metrics
                    ),
                )

            registered += 1

            summaries.append(
                {
                    "candidate_id": (
                        candidate_id
                    ),
                    "horizon": (
                        horizon
                    ),
                    "model_family": (
                        "LSTM"
                    ),
                    "validation_mae": (
                        result.validation_mae
                    ),
                    "test_mae": (
                        result.overall_metrics[
                            "mae"
                        ]
                    ),
                    "best_epoch": (
                        result.best_epoch
                    ),
                    "artifact_path": (
                        stored_path
                    ),
                }
            )

        expected_count = (
            len(
                EXPECTED_HORIZONS
            )
            * len(
                EXPECTED_FAMILIES
            )
        )

        if registered != expected_count:
            raise RuntimeError(
                "Training completed only "
                f"{registered}/"
                f"{expected_count} "
                "candidates"
            )

        with engine.begin() as conn:
            fence_training_job(conn)
            TrainingRepository(
                conn
            ).finish_training_run(
                run_id,
                status="COMPLETED",
                candidate_count=(
                    registered
                ),
            )

        return {
            "status": "COMPLETED",
            "run_id": (
                run_id
            ),
            "business_date": str(
                business_date
            ),
            "data_version": (
                data_version
            ),
            "feature_version": (
                settings.feature_version
            ),
            "candidate_count": (
                registered
            ),
            "candidates": (
                summaries
            ),
        }

    except Exception as exc:
        with engine.begin() as conn:
            fence_training_job(conn)
            TrainingRepository(
                conn
            ).finish_training_run(
                run_id,
                status="FAILED",
                candidate_count=(
                    registered
                ),
                error_message=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )[:4000],
            )

        raise
