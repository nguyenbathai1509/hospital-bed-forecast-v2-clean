from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from src.db.engine import create_sql_engine
from src.evaluation.repository import EvaluationRepository
from src.training.config import EXPECTED_FAMILIES, EXPECTED_HORIZONS, TemporalSplitSpec
from src.training.data import build_sequence_frame
from src.training.lstm import replay_lstm_evaluation
from src.training.tabular import replay_tabular_evaluation


EVALUATION_REPLAY_VERSION = "v2.0"
MAE_ABS_TOLERANCE = 1e-3
EXPECTED_TEST_ROWS_PER_CANDIDATE = 74
EXPECTED_TEST_ROWS_PER_DEPARTMENT = 37
EXPECTED_TOTAL_REPLAY_ROWS = (
    len(EXPECTED_HORIZONS)
    * len(EXPECTED_FAMILIES)
    * EXPECTED_TEST_ROWS_PER_CANDIDATE
)


@dataclass(frozen=True)
class CandidateReplaySummary:
    candidate_id: str
    horizon: int
    model_family: str
    row_count: int
    replay_mae: float
    registry_mae: float
    mae_delta: float

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "horizon": self.horizon,
            "model_family": self.model_family,
            "row_count": self.row_count,
            "replay_mae": self.replay_mae,
            "registry_mae": self.registry_mae,
            "mae_delta": self.mae_delta,
        }


def temporal_split_from_stored(value: dict) -> TemporalSplitSpec:
    required = (
        "train_end",
        "validation_start",
        "validation_end",
        "test_start",
        "test_end",
    )
    missing = [name for name in required if not value.get(name)]
    if missing:
        raise ValueError(f"Stored split_spec is missing fields: {missing}")

    if str(value.get("split_axis", "target_date")) != "target_date":
        raise ValueError("V2-20A replay requires split_axis=target_date")

    shuffle = str(value.get("shuffle", "false")).strip().lower()
    if shuffle not in {"false", "0", "no"}:
        raise ValueError("V2-20A replay requires shuffle=false")

    return TemporalSplitSpec(
        train_end=date.fromisoformat(str(value["train_end"])),
        validation_start=date.fromisoformat(str(value["validation_start"])),
        validation_end=date.fromisoformat(str(value["validation_end"])),
        test_start=date.fromisoformat(str(value["test_start"])),
        test_end=date.fromisoformat(str(value["test_end"])),
    )


def validate_candidate_matrix(candidates: list[dict]) -> None:
    expected = {
        (horizon, family)
        for horizon in EXPECTED_HORIZONS
        for family in EXPECTED_FAMILIES
    }
    actual = {
        (int(row["horizon"]), str(row["model_family"]))
        for row in candidates
    }
    if actual != expected or len(candidates) != len(expected):
        raise RuntimeError(
            "Training Run candidate matrix is incomplete; "
            f"expected={sorted(expected)}, actual={sorted(actual)}"
        )


def _validate_data_version(frame: pd.DataFrame, expected: str | None) -> None:
    if expected is None or "data_version" not in frame.columns:
        return
    actual = {str(value) for value in frame["data_version"].dropna().unique()}
    if actual != {str(expected)}:
        raise RuntimeError(
            "Current ML sample data_version does not match the historical Training Run; "
            f"expected={expected}, actual={sorted(actual)}"
        )


def _prediction_rows(
    *,
    test_frame: pd.DataFrame,
    predictions,
    candidate: dict,
    run_id: str,
) -> tuple[list[dict], CandidateReplaySummary]:
    if len(test_frame) != len(predictions):
        raise RuntimeError("Prediction length does not match TEST rows")

    if len(test_frame) != EXPECTED_TEST_ROWS_PER_CANDIDATE:
        raise RuntimeError(
            "Unexpected TEST row count for V2 contract; "
            f"candidate={candidate['candidate_id']}, got={len(test_frame)}, "
            f"expected={EXPECTED_TEST_ROWS_PER_CANDIDATE}"
        )

    department_counts = (
        test_frame.groupby("department_id").size().astype(int).to_dict()
    )
    if len(department_counts) != 2 or any(
        count != EXPECTED_TEST_ROWS_PER_DEPARTMENT
        for count in department_counts.values()
    ):
        raise RuntimeError(
            "Unexpected TEST department coverage; "
            f"candidate={candidate['candidate_id']}, counts={department_counts}, "
            f"expected=2 departments x {EXPECTED_TEST_ROWS_PER_DEPARTMENT} rows"
        )

    rows: list[dict] = []
    absolute_errors: list[float] = []

    for (_, source), prediction in zip(test_frame.iterrows(), predictions):
        actual = float(source["target_occupied_beds"])
        predicted = float(prediction)
        residual = actual - predicted
        absolute_error = abs(residual)
        absolute_errors.append(absolute_error)
        rows.append(
            {
                "candidate_id": str(candidate["candidate_id"]),
                "run_id": run_id,
                "horizon": int(candidate["horizon"]),
                "model_family": str(candidate["model_family"]),
                "origin_date": pd.Timestamp(source["origin_date"]).date(),
                "target_date": pd.Timestamp(source["target_date"]).date(),
                "department_id": int(source["department_id"]),
                "actual_occupied_beds": actual,
                "prediction_raw": predicted,
                "residual": residual,
                "absolute_error": absolute_error,
                "feature_version": str(candidate["feature_version"]),
                "data_version": candidate.get("data_version"),
                "replay_version": EVALUATION_REPLAY_VERSION,
            }
        )

    replay_mae = float(sum(absolute_errors) / len(absolute_errors))
    registry_mae = float(candidate["mae"])
    delta = abs(replay_mae - registry_mae)

    if not math.isfinite(replay_mae) or delta > MAE_ABS_TOLERANCE:
        raise RuntimeError(
            "Evaluation replay MAE does not reproduce Model Registry evidence; "
            f"candidate={candidate['candidate_id']}, replay_mae={replay_mae:.12f}, "
            f"registry_mae={registry_mae:.12f}, delta={delta:.12f}, "
            f"tolerance={MAE_ABS_TOLERANCE}"
        )

    return rows, CandidateReplaySummary(
        candidate_id=str(candidate["candidate_id"]),
        horizon=int(candidate["horizon"]),
        model_family=str(candidate["model_family"]),
        row_count=len(rows),
        replay_mae=replay_mae,
        registry_mae=registry_mae,
        mae_delta=delta,
    )


def replay_training_evaluation(run_id: str) -> dict:
    engine = create_sql_engine()

    with engine.connect() as conn:
        repo = EvaluationRepository(conn)
        run = repo.training_run(run_id)
        if run is None:
            raise ValueError(f"Training Run not found: {run_id}")
        if run["status"] != "COMPLETED":
            raise RuntimeError(
                f"Evaluation replay requires COMPLETED Training Run; got {run['status']}"
            )

        existing_count = repo.prediction_count(run_id)
        if existing_count > 0:
            counts = repo.prediction_counts_by_candidate(run_id)
            metrics = repo.replay_metrics(run_id)
            return {
                "status": "ALREADY_REPLAYED",
                "run_id": run_id,
                "prediction_count": existing_count,
                "candidate_counts": counts,
                "metrics": metrics,
            }

        candidates = repo.candidates(run_id)
        validate_candidate_matrix(candidates)
        split_spec = temporal_split_from_stored(run["split_spec"])
        random_seed = int(run["random_seed"])
        feature_version = str(run["feature_version"])

        tabular_frames = {
            horizon: pd.DataFrame(
                repo.fetch_tabular_dataset(horizon, feature_version)
            )
            for horizon in EXPECTED_HORIZONS
        }
        for frame in tabular_frames.values():
            _validate_data_version(frame, run.get("data_version"))

        feature_history = repo.fetch_feature_history(feature_version)
        sample_rows = {
            horizon: repo.fetch_ml_samples(horizon, feature_version)
            for horizon in EXPECTED_HORIZONS
        }

    all_rows: list[dict] = []
    summaries: list[CandidateReplaySummary] = []
    sequence_cache: dict[tuple[int, tuple[int, ...]], pd.DataFrame] = {}

    for candidate in candidates:
        horizon = int(candidate["horizon"])
        family = str(candidate["model_family"])

        if family in {"RF", "XGBOOST", "SVR"}:
            test_frame, predictions = replay_tabular_evaluation(
                frame=tabular_frames[horizon],
                model_family=family,
                best_params=dict(candidate["best_params"]),
                random_seed=random_seed,
                split_spec=split_spec,
            )
        elif family == "LSTM":
            metadata = dict(candidate["model_metadata"])
            categories = tuple(
                int(value)
                for value in metadata.get("department_categories", [])
            )
            if not categories:
                raise RuntimeError(
                    f"LSTM candidate missing department_categories: {candidate['candidate_id']}"
                )
            cache_key = (horizon, categories)
            if cache_key not in sequence_cache:
                sequence_cache[cache_key] = build_sequence_frame(
                    feature_rows=feature_history,
                    sample_rows=sample_rows[horizon],
                    department_categories=categories,
                )
            best_epoch = int(metadata.get("best_epoch") or 0)
            if best_epoch <= 0:
                raise RuntimeError(
                    f"LSTM candidate missing best_epoch: {candidate['candidate_id']}"
                )
            test_frame, predictions = replay_lstm_evaluation(
                sequence_frame=sequence_cache[cache_key],
                best_params=dict(candidate["best_params"]),
                best_epoch=best_epoch,
                random_seed=random_seed,
                split_spec=split_spec,
            )
        else:
            raise RuntimeError(f"Unsupported model family: {family}")

        rows, summary = _prediction_rows(
            test_frame=test_frame,
            predictions=predictions,
            candidate=candidate,
            run_id=run_id,
        )
        all_rows.extend(rows)
        summaries.append(summary)

    expected_total = (
        len(EXPECTED_HORIZONS)
        * len(EXPECTED_FAMILIES)
        * EXPECTED_TEST_ROWS_PER_CANDIDATE
    )
    if len(all_rows) != expected_total:
        raise RuntimeError(
            f"Unexpected total replay rows: got={len(all_rows)}, expected={expected_total}"
        )

    # Persist only after all 8 candidates have reproduced their registry MAE.
    with engine.begin() as conn:
        repo = EvaluationRepository(conn)
        if repo.prediction_count(run_id) != 0:
            raise RuntimeError(
                "Evaluation evidence appeared concurrently; aborting to preserve immutability"
            )
        repo.insert_predictions(all_rows)

    return {
        "status": "COMPLETED",
        "run_id": run_id,
        "prediction_count": len(all_rows),
        "candidate_count": len(summaries),
        "test_rows_per_candidate": EXPECTED_TEST_ROWS_PER_CANDIDATE,
        "test_rows_per_department": EXPECTED_TEST_ROWS_PER_DEPARTMENT,
        "mae_abs_tolerance": MAE_ABS_TOLERANCE,
        "summaries": [item.as_dict() for item in summaries],
    }