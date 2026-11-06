from __future__ import annotations

from src.training.job_context import fence_training_job

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from src.db.engine import create_sql_engine
from src.evaluation.repository import EvaluationRepository
from src.training.config import EXPECTED_FAMILIES, EXPECTED_HORIZONS, TemporalSplitSpec
from src.training.data import build_sequence_frame, split_by_target_date
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


def _expected_test_department_counts(
    *,
    sample_rows: list[dict],
    split_spec: TemporalSplitSpec,
) -> dict[int, int]:
    if not sample_rows:
        raise RuntimeError(
            "Historical ML samples are empty"
        )

    sample_frame = pd.DataFrame(
        sample_rows
    )

    test_frame = (
        split_by_target_date(
            sample_frame,
            split_spec,
        ).test
    )

    counts = {
        int(department_id): int(count)
        for department_id, count
        in (
            test_frame
            .groupby("department_id")
            .size()
            .astype(int)
            .to_dict()
            .items()
        )
    }

    if not counts:
        raise RuntimeError(
            "Historical TEST department "
            "coverage is empty"
        )

    expected_days = (split_spec.test_end - split_spec.test_start).days + 1
    if test_frame.duplicated(["department_id", "target_date"]).any():
        raise RuntimeError("Duplicate historical TEST department/date rows")

    invalid = {
        department_id: count
        for department_id, count
        in counts.items()
        if count
        != expected_days
    }

    if invalid:
        raise RuntimeError(
            "Unexpected historical TEST "
            "department coverage; "
            f"counts={counts}, "
            "expected each department="
            f"{expected_days} "
            "rows"
        )

    return dict(
        sorted(
            counts.items()
        )
    )


def _prediction_rows(
    *,
    test_frame: pd.DataFrame,
    predictions,
    candidate: dict,
    run_id: str,
    expected_department_counts: (
        dict[int, int]
        | None
    ) = None,
) -> tuple[list[dict], CandidateReplaySummary]:
    if len(test_frame) != len(predictions):
        raise RuntimeError("Prediction length does not match TEST rows")

    department_counts = {
        int(department_id): int(count)
        for department_id, count
        in (
            test_frame
            .groupby("department_id")
            .size()
            .astype(int)
            .to_dict()
            .items()
        )
    }

    expected_counts = (
        dict(
            department_counts
        )
        if expected_department_counts
        is None
        else {
            int(department_id):
                int(count)
            for department_id, count
            in expected_department_counts.items()
        }
    )

    if not expected_counts:
        raise RuntimeError(
            "Expected TEST department "
            "coverage is empty"
        )

    invalid_expected = {
        department_id: count
        for department_id, count
        in expected_counts.items()
        if count <= 0
    }

    if invalid_expected:
        raise RuntimeError(
            "Historical TEST coverage "
            "must contain positive per-department counts; "
            f"counts={expected_counts}"
        )

    if test_frame.duplicated(["department_id", "target_date"]).any():
        raise RuntimeError("Duplicate replay TEST department/date rows")

    if (
        department_counts
        != expected_counts
    ):
        raise RuntimeError(
            "Replay TEST department coverage "
            "does not match historical "
            "ML samples; "
            f"candidate={candidate['candidate_id']}, "
            f"actual={department_counts}, "
            f"expected={expected_counts}"
        )

    expected_test_rows = sum(
        expected_counts.values()
    )

    if (
        len(test_frame)
        != expected_test_rows
    ):
        raise RuntimeError(
            "Unexpected TEST row count; "
            f"candidate={candidate['candidate_id']}, "
            f"got={len(test_frame)}, "
            f"expected={expected_test_rows}"
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
            if not repo.evaluation_evidence_complete(run_id):
                raise RuntimeError(
                    "Stored evaluation evidence is incomplete or inconsistent with "
                    "registered TEST sample counts; existing evidence was not changed"
                )
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

        expected_department_counts_by_horizon = {
            horizon:
                _expected_test_department_counts(
                    sample_rows=(
                        sample_rows[
                            horizon
                        ]
                    ),
                    split_spec=split_spec,
                )
            for horizon
            in EXPECTED_HORIZONS
        }

        coverage_signatures = {
            tuple(
                counts.items()
            )
            for counts
            in (
                expected_department_counts_by_horizon
                .values()
            )
        }

        if len(
            coverage_signatures
        ) != 1:
            raise RuntimeError(
                "Historical TEST department "
                "coverage differs across "
                "horizons; "
                "counts="
                f"{expected_department_counts_by_horizon}"
            )

        test_rows_per_candidate = sum(
            next(
                iter(
                    expected_department_counts_by_horizon
                    .values()
                )
            ).values()
        )

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
            expected_department_counts=(
                expected_department_counts_by_horizon[
                    horizon
                ]
            ),
        )
        all_rows.extend(rows)
        summaries.append(summary)

    expected_total = (
        len(EXPECTED_HORIZONS)
        * len(EXPECTED_FAMILIES)
        * test_rows_per_candidate
    )
    if len(all_rows) != expected_total:
        raise RuntimeError(
            f"Unexpected total replay rows: got={len(all_rows)}, expected={expected_total}"
        )

    # Persist only after all 8 candidates have reproduced their registry MAE.
    with engine.begin() as conn:
        fence_training_job(conn)
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
        "test_rows_per_candidate": test_rows_per_candidate,
        "test_rows_per_department": (split_spec.test_end - split_spec.test_start).days + 1,
        "mae_abs_tolerance": MAE_ABS_TOLERANCE,
        "summaries": [item.as_dict() for item in summaries],
    }
