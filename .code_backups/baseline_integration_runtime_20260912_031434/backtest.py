"""Read-only, expanding-history comparison of frozen model configurations.

No Production artifact is used or overwritten. Parameters/epochs stay frozen;
weights are fit afresh before each scoring block. Final audit dates never enter
the ranking or recommendation decision.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.db.engine import create_sql_engine
from src.evaluation.repository import EvaluationRepository
from src.evaluation.service import temporal_split_from_stored, _validate_data_version
from src.recommendation.config import RecommendationPolicy
from src.recommendation.contracts import CandidateMetrics, DepartmentMetrics, RecommendationDecision
from src.recommendation.engine import decide_recommendation, rank_candidates
from src.training.config import TemporalSplitSpec
from src.training.data import build_sequence_frame
from src.training.lstm import replay_lstm_evaluation
from src.training.tabular import replay_tabular_evaluation
from src.training.metrics import compute_regression_metrics, compute_metrics_by_department
from src.training.environment import capture_code_revision, capture_environment


BACKTEST_VERSION = "common-window-v1"


class InsufficientComparisonData(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    fit_end: date

    def as_dict(self) -> dict:
        return {"start": str(self.start), "end": str(self.end), "fit_end": str(self.fit_end)}


@dataclass(frozen=True)
class BacktestPlan:
    folds: tuple[Window, ...]
    audit: Window

    def as_dict(self) -> dict:
        return {"folds": [fold.as_dict() for fold in self.folds], "audit": self.audit.as_dict()}


@dataclass(frozen=True)
class BacktestResult:
    decision: RecommendationDecision
    ranked: list[CandidateMetrics]
    evidence: dict


def plan_windows(
    split: TemporalSplitSpec, *, horizon: int, configuration_known_through: date,
    fold_count: int = 3, min_fold_days: int = 7, audit_days: int = 7,
) -> BacktestPlan:
    if horizon not in (1, 3):
        raise ValueError("Unsupported backtest horizon")
    if any(type(v) is not int or v < 1 for v in (fold_count, min_fold_days, audit_days)):
        raise ValueError("Backtest window sizes must be positive integers")
    # At the first prediction origin, all labels used to select parameters must
    # already be available. For H+3, purge the two intervening target days.
    start = max(split.test_start, max(split.validation_end, configuration_known_through) + timedelta(days=horizon))
    audit_start = split.test_end - timedelta(days=audit_days - 1)
    selection_days = (audit_start - start).days
    if selection_days < fold_count * min_fold_days:
        raise InsufficientComparisonData(
            f"Cần ít nhất {fold_count * min_fold_days + audit_days} ngày đánh giá chung "
            f"kể từ {start}; hiện có {max(0, (split.test_end - start).days + 1)} ngày."
        )
    base, remainder = divmod(selection_days, fold_count)
    folds = []
    for index in range(fold_count):
        end = start + timedelta(days=base + (index < remainder) - 1)
        folds.append(Window(start, end, start - timedelta(days=horizon)))
        start = end + timedelta(days=1)
    return BacktestPlan(tuple(folds), Window(audit_start, split.test_end, audit_start - timedelta(days=horizon)))


def _validate_coverage(frame: pd.DataFrame, plan: BacktestPlan) -> None:
    required = {"origin_date", "target_date", "department_id", "target_occupied_beds"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("Backtest requires dated, non-empty samples with actuals")
    if frame[list(required)].isna().any().any():
        raise ValueError("Backtest samples contain missing keys or actuals")
    if frame.duplicated(["department_id", "target_date"]).any():
        raise ValueError("Backtest contains duplicate department/date samples")
    departments = set(frame.department_id.astype(int))
    expected_dates = pd.date_range(plan.folds[0].start, plan.audit.end).date
    expected = {(d, day) for d in departments for day in expected_dates}
    actual = {(int(r.department_id), r.target_date) for r in frame.itertuples() if r.target_date >= plan.folds[0].start}
    if actual != expected:
        raise InsufficientComparisonData("Thiếu ngày hoặc khoa trong cửa sổ đánh giá chung.")


def _score_block(
    *, details: dict, frame: pd.DataFrame, feature_history: list[dict],
    split: TemporalSplitSpec, window: Window, seed: int,
) -> pd.DataFrame:
    """Fit only labels available at block's first origin; never write artifacts."""
    block_frame = frame[frame.target_date <= window.end].copy()
    fold_spec = TemporalSplitSpec(
        train_end=split.train_end, validation_start=split.validation_start,
        validation_end=window.fit_end, test_start=window.fit_end + timedelta(days=1),
        test_end=window.end,
    )
    params = dict(details["best_params"])
    if details["model_family"] == "LSTM":
        metadata = details["model_metadata"]
        categories = tuple(int(d) for d in metadata.get("department_categories", []))
        if set(categories) != set(frame.department_id.astype(int)):
            raise InsufficientComparisonData("Cấu hình LSTM chưa bao phủ cùng danh sách khoa.")
        sequence = build_sequence_frame(
            feature_rows=feature_history, sample_rows=block_frame.to_dict("records"),
            department_categories=categories,
        )
        evaluated, predictions = replay_lstm_evaluation(
            sequence_frame=sequence, best_params=params,
            best_epoch=int(metadata.get("best_epoch") or 0), random_seed=seed, split_spec=fold_spec,
        )
    else:
        evaluated, predictions = replay_tabular_evaluation(
            frame=block_frame, model_family=details["model_family"], best_params=params,
            random_seed=seed, split_spec=fold_spec,
        )
    if len(evaluated) != len(predictions) or not np.isfinite(predictions).all():
        raise ValueError("Backtest returned invalid predictions")
    evaluated = evaluated[["department_id", "origin_date", "target_date", "target_occupied_beds"]].copy()
    evaluated["prediction_raw"] = predictions
    evaluated = evaluated[evaluated.target_date >= window.start].reset_index(drop=True)
    expected = block_frame[block_frame.target_date >= window.start]
    expected_keys = list(zip(expected.department_id, expected.target_date))
    if list(zip(evaluated.department_id, evaluated.target_date)) != expected_keys:
        raise ValueError("Backtest prediction keys do not match scoring samples")
    return evaluated



BASELINE_NAMES = (
    "LAST_VALUE",
    "SEASONAL_NAIVE_7",
    "MOVING_AVERAGE_7",
)


def _score_baseline_block(
    *,
    baseline_name: str,
    frame: pd.DataFrame,
    feature_history: list[dict],
    window: Window,
) -> pd.DataFrame:
    """Score a simple benchmark using only information known at origin_date.

    Baselines are benchmark-only. This function does not fit or persist any
    model artifact and does not participate in Recommendation ranking.
    """

    if baseline_name not in BASELINE_NAMES:
        raise ValueError(
            f"Unsupported baseline_name={baseline_name!r}; "
            f"expected one of {BASELINE_NAMES}"
        )

    required_frame = {
        "department_id",
        "origin_date",
        "target_date",
        "target_occupied_beds",
    }

    if not required_frame.issubset(frame.columns):
        missing = sorted(required_frame - set(frame.columns))
        raise ValueError(
            f"Baseline frame is missing required columns: {missing}"
        )

    history = pd.DataFrame(feature_history)

    required_history = {
        "origin_date",
        "department_id",
        "occupied_beds",
    }

    if history.empty or not required_history.issubset(history.columns):
        missing = sorted(required_history - set(history.columns))
        raise InsufficientComparisonData(
            f"{baseline_name}: feature history is missing required "
            f"columns or rows: {missing}"
        )

    scoring = frame[
        (frame["target_date"] >= window.start)
        & (frame["target_date"] <= window.end)
    ].copy()

    if scoring.empty:
        raise InsufficientComparisonData(
            f"{baseline_name}: no scoring rows in requested window"
        )

    for column in ("origin_date", "target_date"):
        scoring[column] = pd.to_datetime(
            scoring[column],
            errors="raise",
        ).dt.date

    history = history[
        ["origin_date", "department_id", "occupied_beds"]
    ].copy()

    history["origin_date"] = pd.to_datetime(
        history["origin_date"],
        errors="raise",
    ).dt.date

    if history[
        ["origin_date", "department_id", "occupied_beds"]
    ].isna().any().any():
        raise InsufficientComparisonData(
            f"{baseline_name}: feature history contains missing values"
        )

    if history.duplicated(
        ["department_id", "origin_date"]
    ).any():
        raise ValueError(
            "Baseline feature history contains duplicate department/date rows"
        )

    history["department_id"] = history["department_id"].astype(int)
    history["occupied_beds"] = pd.to_numeric(
        history["occupied_beds"],
        errors="raise",
    ).astype(float)

    history_lookup = {
        (int(row.department_id), row.origin_date): float(row.occupied_beds)
        for row in history.itertuples()
    }

    predictions: list[float] = []

    for row in scoring.itertuples():
        department_id = int(row.department_id)
        origin_date = row.origin_date
        target_date = row.target_date

        if target_date <= origin_date:
            raise ValueError(
                "Baseline scoring requires target_date after origin_date"
            )

        if baseline_name == "LAST_VALUE":
            required_dates = [origin_date]

        elif baseline_name == "SEASONAL_NAIVE_7":
            reference_date = target_date - timedelta(days=7)

            if reference_date > origin_date:
                raise ValueError(
                    "SEASONAL_NAIVE_7 would require information after "
                    "origin_date"
                )

            required_dates = [reference_date]

        else:
            required_dates = [
                origin_date - timedelta(days=offset)
                for offset in range(6, -1, -1)
            ]

        values: list[float] = []

        for required_date in required_dates:
            key = (department_id, required_date)

            if key not in history_lookup:
                raise InsufficientComparisonData(
                    f"{baseline_name}: missing occupied_beds for "
                    f"department={department_id}, date={required_date}"
                )

            values.append(history_lookup[key])

        if baseline_name == "MOVING_AVERAGE_7":
            prediction = float(np.mean(values))
        else:
            prediction = float(values[0])

        if not np.isfinite(prediction):
            raise ValueError(
                f"{baseline_name}: produced a non-finite prediction"
            )

        predictions.append(prediction)

    result = scoring[
        [
            "department_id",
            "origin_date",
            "target_date",
            "target_occupied_beds",
        ]
    ].copy()

    result["prediction_raw"] = predictions

    return result.reset_index(drop=True)

def _metrics(candidate: CandidateMetrics, rows: pd.DataFrame, window_spec: dict):
    overall = compute_regression_metrics(rows.target_occupied_beds, rows.prediction_raw).as_dict()
    overall.pop("sample_count")
    by_department = compute_metrics_by_department(rows.department_id, rows.target_occupied_beds, rows.prediction_raw)
    return (
        replace(candidate, split_spec=window_spec, **overall),
        {dep: DepartmentMetrics(candidate_id=candidate.candidate_id, department_id=dep, **metrics.as_dict())
         for dep, metrics in by_department.items()},
    )


def compare_configurations(
    *, candidates: list[CandidateMetrics], champion: CandidateMetrics, champion_source: str,
    details: dict[str, dict], frame: pd.DataFrame, feature_history: list[dict],
    split: TemporalSplitSpec, known_through: date, seed: int, data_version: str,
    policy: RecommendationPolicy,
) -> BacktestResult:
    """Pure orchestration over a supplied snapshot (no database writes)."""
    plan = plan_windows(
        split, horizon=champion.horizon, configuration_known_through=known_through,
        fold_count=policy.backtest_folds, min_fold_days=policy.backtest_min_fold_days,
        audit_days=policy.backtest_audit_days,
    )
    frame = frame.copy()
    for column in ("origin_date", "target_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date
    frame = frame.sort_values(["target_date", "department_id"], kind="stable").reset_index(drop=True)
    if not all((t - o).days == champion.horizon for o, t in zip(frame.origin_date, frame.target_date)):
        raise ValueError("Backtest origin/target dates do not match horizon")
    _validate_coverage(frame, plan)
    participants = {c.candidate_id: c for c in [*candidates, champion]}
    if not candidates or set(participants) != set(details):
        raise ValueError("Backtest requires details for exactly the compared candidates")
    if any(c.horizon != champion.horizon for c in participants.values()):
        raise ValueError("Backtest candidates must share the same horizon")
    common_spec = {"version": BACKTEST_VERSION, "data_version": data_version,
                   "horizon": champion.horizon, "selection": [w.as_dict() for w in plan.folds]}
    measured, department_metrics, summaries, evidence_rows = {}, {}, [], []
    for candidate_id, candidate in participants.items():
        blocks = []
        for index, window in enumerate(plan.folds, start=1):
            rows = _score_block(
                details=details[candidate_id], frame=frame, feature_history=feature_history,
                split=split, window=window, seed=seed,
            )
            blocks.append(rows)
            summaries.append({"candidate_id": candidate_id, "model_family": candidate.model_family,
                              "fold": index, **window.as_dict(),
                              **compute_regression_metrics(rows.target_occupied_beds, rows.prediction_raw).as_dict()})
            evidence_rows.extend({"candidate_id": candidate_id, "fold": index, **r} for r in rows.to_dict("records"))
        pooled = pd.concat(blocks, ignore_index=True)
        measured[candidate_id], department_metrics[candidate_id] = _metrics(candidate, pooled, common_spec)
    ranked = rank_candidates([measured[c.candidate_id] for c in candidates])
    decision = decide_recommendation(
        ranked_candidates=ranked, champion=measured[champion.candidate_id],
        champion_source=champion_source, metrics_by_candidate_department=department_metrics, policy=policy,
    )
    # Decision is frozen before inspecting the audit block. Audit is descriptive;
    # no retry, alternate candidate selection, or promotion veto based on its MAE.
    audit = []
    for candidate_id in dict.fromkeys([decision.recommended_candidate_id, champion.candidate_id]):
        rows = _score_block(
            details=details[candidate_id], frame=frame, feature_history=feature_history,
            split=split, window=plan.audit, seed=seed,
        )
        audit.append({"candidate_id": candidate_id, "model_family": participants[candidate_id].model_family,
                      **compute_regression_metrics(rows.target_occupied_beds, rows.prediction_raw).as_dict()})
        evidence_rows.extend({"candidate_id": candidate_id, "fold": "AUDIT", **r} for r in rows.to_dict("records"))
    payload = {
        "status": "COMPLETED", "version": BACKTEST_VERSION,
        "environment": capture_environment(),
        "code_revision": capture_code_revision(Path(__file__).resolve().parents[2]),
        "mode": "REFIT_FROZEN_CONFIGURATIONS", "random_seed": seed,
        "data_version": data_version, "configuration_known_through": str(known_through),
        **plan.as_dict(), "fold_metrics": summaries, "audit_metrics": audit,
        "champion_id": champion.candidate_id, "decision_uses_audit": False,
        "selection_metrics": [dict(candidate_id=k, mae=v.mae, rmse=v.rmse, bias=v.bias) for k, v in measured.items()],
        "department_metrics": {k: [vars(v) for v in metrics.values()] for k, metrics in department_metrics.items()},
        "configurations": {k: dict(model_family=v["model_family"], best_params=v["best_params"],
                                    model_metadata=v["model_metadata"]) for k, v in details.items()},
        "input_sha256": hashlib.sha256((frame.to_json(orient="split", date_format="iso") +
            json.dumps(feature_history, sort_keys=True, default=str)).encode()).hexdigest(),
        "predictions": evidence_rows,
    }
    # Convert date/numpy values once, producing an ordinary JSON-compatible snapshot.
    payload = json.loads(json.dumps(payload, default=str, allow_nan=False))
    return BacktestResult(decision, ranked, payload)


def backtest_recommendation(
    *, run_id: str, candidates: list[CandidateMetrics], champion: CandidateMetrics,
    champion_source: str, policy: RecommendationPolicy,
) -> BacktestResult:
    engine = create_sql_engine()
    with engine.connect() as conn:
        repo = EvaluationRepository(conn)
        run = repo.training_run(run_id)
        if run is None or run["status"] != "COMPLETED":
            raise ValueError("Backtest requires a completed Training Run")
        split = temporal_split_from_stored(run["split_spec"])
        current = {r["candidate_id"]: r for r in repo.candidates(run_id) if int(r["horizon"]) == champion.horizon}
        needed = {c.candidate_id for c in candidates}
        if set(current) != needed:
            raise ValueError("Backtest candidate matrix does not match Training Run")
        known_through = split.validation_end
        if champion.run_id != run_id:
            old_run = repo.training_run(champion.run_id)
            if old_run is None or old_run["status"] != "COMPLETED":
                raise ValueError("Champion Training Run is missing or incomplete")
            # Champion family may have been selected using its historical TEST.
            # Exclude that whole period, not merely its tuning validation dates.
            old_split = temporal_split_from_stored(old_run["split_spec"])
            known_through = max(known_through, old_split.test_end, pd.Timestamp(old_run["data_end"]).date())
            old = {r["candidate_id"]: r for r in repo.candidates(champion.run_id)}
            current[champion.candidate_id] = old[champion.candidate_id]
        if any(r["feature_version"] != run["feature_version"] for r in current.values()):
            raise InsufficientComparisonData("Phiên bản đặc trưng của hai mô hình khác nhau; cần đánh giá tương thích.")
        # Plan before loading data or fitting any model if there are too few new days.
        plan_windows(split, horizon=champion.horizon, configuration_known_through=known_through,
                     fold_count=policy.backtest_folds, min_fold_days=policy.backtest_min_fold_days,
                     audit_days=policy.backtest_audit_days)
        frame = pd.DataFrame(repo.fetch_tabular_dataset(champion.horizon, run["feature_version"]))
        _validate_data_version(frame, run["data_version"])
        feature_history = repo.fetch_feature_history(run["feature_version"])
    return compare_configurations(
        candidates=candidates, champion=champion, champion_source=champion_source,
        details=current, frame=frame, feature_history=feature_history, split=split,
        known_through=known_through, seed=int(run["random_seed"]), data_version=str(run["data_version"]), policy=policy,
    )
