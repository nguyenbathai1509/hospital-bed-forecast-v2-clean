from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.features.builder import FEATURE_VALUE_COLUMNS
from src.recommendation import backtest as bt
from src.recommendation.config import RecommendationPolicy
from src.recommendation.contracts import CandidateMetrics
from src.training.config import TemporalSplitSpec
from src.training.data import split_by_target_date
from src.training.metrics import compute_regression_metrics


SPLIT = TemporalSplitSpec.ending_at(date(2026, 8, 31))
POLICY = RecommendationPolicy()


def candidate(name, family="RF", horizon=1, run_id="NEW"):
    metrics = compute_regression_metrics([50, 51], [48, 49]).as_dict()
    metrics.pop("sample_count")
    return CandidateMetrics(candidate_id=name, run_id=run_id, horizon=horizon,
                            model_family=family, split_spec=SPLIT.as_dict(), **metrics)


def samples(horizon=1):
    records = []
    for day in pd.date_range("2026-05-01", "2026-08-31"):
        for department in (343, 344):
            row = {name: 1.0 for name in FEATURE_VALUE_COLUMNS}
            row.update(department_id=department, horizon=horizon, target_date=day.date(),
                       origin_date=day.date() - timedelta(days=horizon),
                       target_occupied_beds=50.0, data_version="NEW_DATA")
            records.append(row)
    return pd.DataFrame(records)


def details_for(*candidates):
    return {c.candidate_id: dict(candidate_id=c.candidate_id, model_family=c.model_family,
                horizon=c.horizon, feature_version="v2.0", best_params={"n_estimators": 3, "max_depth": 2},
                model_metadata={"best_epoch": 1, "department_categories": [343, 344]}) for c in candidates}


@pytest.mark.parametrize("horizon,first_day", [(1, date(2026, 7, 26)), (3, date(2026, 7, 28))])
def test_fold_plan_purges_unavailable_labels_and_reserves_audit(horizon, first_day):
    plan = bt.plan_windows(SPLIT, horizon=horizon, configuration_known_through=date(2026, 6, 30))
    assert len(plan.folds) == 3
    assert plan.folds[0].start == first_day
    assert plan.audit.start == date(2026, 8, 25)
    dates = []
    for block in (*plan.folds, plan.audit):
        assert block.fit_end == block.start - timedelta(days=horizon)
        assert block.fit_end >= SPLIT.validation_end
        dates.extend(pd.date_range(block.start, block.end).date)
    assert len(dates) == len(set(dates))
    assert dates == list(pd.date_range(first_day, SPLIT.test_end).date)


def test_recent_champion_does_not_allow_retrospective_selection_leakage():
    with pytest.raises(bt.InsufficientComparisonData, match="ngày"):
        bt.plan_windows(SPLIT, horizon=3, configuration_known_through=date(2026, 8, 10))


@pytest.mark.parametrize("kwargs", [{"fold_count": 0}, {"min_fold_days": -1}, {"audit_days": True}])
def test_invalid_backtest_configuration_rejected(kwargs):
    with pytest.raises(ValueError, match="positive"):
        bt.plan_windows(SPLIT, horizon=1, configuration_known_through=SPLIT.validation_end, **kwargs)


def fake_scorer(calls):
    def score(*, details, frame, window, **kwargs):
        name = details["candidate_id"]
        calls.append((name, window))
        rows = frame[(frame.target_date >= window.start) & (frame.target_date <= window.end)].copy()
        # Predictions fixed independently of actuals, including the audit block.
        rows["prediction_raw"] = {"NEW_RF": 49.5, "NEW_SVR": 49, "OLD": 48}[name]
        return rows
    return score


def test_audit_actuals_cannot_change_ranking_or_decision(monkeypatch):
    challenger, alternate, champion = candidate("NEW_RF"), candidate("NEW_SVR", "SVR"), candidate("OLD", run_id="OLD_RUN")
    calls = []
    monkeypatch.setattr(bt, "_score_block", fake_scorer(calls))
    args = dict(candidates=[challenger, alternate], champion=champion, champion_source="PRODUCTION",
                details=details_for(challenger, alternate, champion), feature_history=[], split=SPLIT,
                known_through=SPLIT.validation_end, seed=42, data_version="NEW_DATA", policy=POLICY)
    frame = samples()
    result = bt.compare_configurations(frame=frame, **args)
    assert result.decision.action == "PROMOTE"
    assert result.decision.recommended_candidate_id == "NEW_RF"
    assert result.decision.guardrail_pass
    assert result.evidence["decision_uses_audit"] is False
    assert len(result.evidence["fold_metrics"]) == 9
    # Only selected configuration and champion enter audit, after all selection folds.
    assert [name for name, _ in calls[-2:]] == ["NEW_RF", "OLD"]
    assert all(window.start < date(2026, 8, 25) for _, window in calls[:-2])
    altered = frame.copy()
    altered.loc[altered.target_date >= date(2026, 8, 25), "target_occupied_beds"] = 500
    changed = bt.compare_configurations(frame=altered, **args)
    assert changed.decision == result.decision
    assert changed.ranked == result.ranked
    assert changed.evidence["audit_metrics"] != result.evidence["audit_metrics"]
    assert changed.evidence["input_sha256"] != result.evidence["input_sha256"]
    # Original registry evidence was not replaced with comparison metrics.
    assert challenger.mae == champion.mae == 2
    assert result.ranked[0].mae == .5


def test_missing_day_duplicate_or_wrong_horizon_rejected_before_fit(monkeypatch):
    challenger, champion = candidate("NEW_RF"), candidate("OLD", run_id="OLD_RUN")
    def no_fit(**kwargs):
        pytest.fail("Invalid samples must fail before fitting")
    monkeypatch.setattr(bt, "_score_block", no_fit)
    args = dict(candidates=[challenger], champion=champion, champion_source="PRODUCTION",
                details=details_for(challenger, champion), feature_history=[], split=SPLIT,
                known_through=SPLIT.validation_end, seed=42, data_version="NEW_DATA", policy=POLICY)
    frame = samples()
    with pytest.raises(bt.InsufficientComparisonData, match="Thiếu"):
        bt.compare_configurations(frame=frame.iloc[:-1], **args)
    with pytest.raises(ValueError, match="duplicate"):
        bt.compare_configurations(frame=pd.concat([frame, frame.tail(1)]), **args)
    with pytest.raises(ValueError, match="horizon"):
        bt.compare_configurations(frame=samples(horizon=3), **args)


def test_h3_block_fit_ends_at_first_origin_and_gap_predictions_are_not_scored(monkeypatch):
    frame = samples(horizon=3)
    window = bt.plan_windows(SPLIT, horizon=3, configuration_known_through=SPLIT.validation_end).folds[0]
    def replay(*, frame, split_spec, **kwargs):
        partitions = split_by_target_date(frame, split_spec)
        assert partitions.development.target_date.max() == window.start - timedelta(days=3)
        assert partitions.development.target_date.max() < partitions.test.origin_date.min() + timedelta(days=3)
        return partitions.test, np.full(len(partitions.test), 49.0)
    monkeypatch.setattr(bt, "replay_tabular_evaluation", replay)
    c = candidate("NEW_RF", horizon=3)
    result = bt._score_block(details=details_for(c)[c.candidate_id], frame=frame,
                            feature_history=[], split=SPLIT, window=window, seed=42)
    assert result.target_date.min() == window.start
    assert result.target_date.max() == window.end
    assert len(result) == ((window.end - window.start).days + 1) * 2


def test_real_small_rf_backtest_uses_common_window_and_creates_no_artifacts(tmp_path, monkeypatch):
    # Actual sklearn fitting; no TensorFlow or DB required for this regression.
    monkeypatch.chdir(tmp_path)
    current, old = candidate("NEW_RF"), candidate("OLD", run_id="OLD_RUN")
    outcome = bt.compare_configurations(
        candidates=[current], champion=old, champion_source="PRODUCTION",
        details=details_for(current, old), frame=samples(), feature_history=[], split=SPLIT,
        known_through=SPLIT.validation_end, seed=42, data_version="NEW_DATA", policy=POLICY,
    )
    assert outcome.decision.action == "KEEP"
    assert outcome.decision.improvement_pct == 0
    assert len(outcome.evidence["fold_metrics"]) == 6
    assert list(tmp_path.iterdir()) == []


def test_loader_uses_champion_selection_cutoff_and_new_data_version(monkeypatch):
    current, old = candidate("NEW_RF"), candidate("OLD", run_id="OLD_RUN")
    detail_map = details_for(current, old)
    captured = {}
    class Engine:
        @contextmanager
        def connect(self):
            yield object()
    class Repo:
        def __init__(self, conn):
            pass
        def training_run(self, run_id):
            spec = SPLIT if run_id == "NEW" else TemporalSplitSpec.ending_at(date(2026, 7, 31))
            return dict(status="COMPLETED", split_spec=spec.as_dict(), data_end=spec.test_end,
                        feature_version="v2.0", data_version="NEW_DATA", random_seed=42)
        def candidates(self, run_id):
            return [detail_map["NEW_RF" if run_id == "NEW" else "OLD"]]
        def fetch_tabular_dataset(self, horizon, feature_version):
            return samples().to_dict("records")
        def fetch_feature_history(self, feature_version):
            return []
    monkeypatch.setattr(bt, "create_sql_engine", Engine)
    monkeypatch.setattr(bt, "EvaluationRepository", Repo)
    def compare(**kwargs):
        captured.update(kwargs)
        return "result"
    monkeypatch.setattr(bt, "compare_configurations", compare)
    assert bt.backtest_recommendation(run_id="NEW", candidates=[current], champion=old,
               champion_source="PRODUCTION", policy=POLICY) == "result"
    assert captured["known_through"] == date(2026, 7, 31)
    assert captured["data_version"] == "NEW_DATA"


def test_recommendation_service_keeps_champion_when_common_window_is_insufficient(monkeypatch):
    from src.recommendation import service
    saved = []
    current = {h: [candidate(f"{h}_{f}", family=f, horizon=h) for f in ("RF", "XGBOOST", "SVR", "LSTM")] for h in (1, 3)}
    champions = {h: candidate(f"OLD_{h}", horizon=h, run_id="OLD_RUN") for h in (1, 3)}
    class Engine:
        @contextmanager
        def connect(self):
            yield object()
        begin = connect
    class Repo:
        def __init__(self, conn):
            pass
        def get_training_run(self, run_id):
            return dict(run_id=run_id, status="COMPLETED", business_date=date(2026, 8, 31))
        def get_existing_recommendation(self, run_id, horizon):
            return None
        def list_candidates_for_run_horizon(self, run_id, horizon):
            return current[horizon]
        def metrics_by_department(self, ids):
            return {}
        def active_production_candidate_id(self, horizon, *, for_update=False):
            return champions[horizon].candidate_id
        def get_candidate_metrics(self, candidate_id):
            return next(c for c in champions.values() if c.candidate_id == candidate_id)
        def save_recommendation(self, **kwargs):
            saved.append(kwargs)
    def unavailable(**kwargs):
        raise bt.InsufficientComparisonData("Chưa đủ ngày mới")
    monkeypatch.setattr(service, "create_sql_engine", Engine)
    monkeypatch.setattr(service, "RecommendationRepository", Repo)
    monkeypatch.setattr(service, "backtest_recommendation", unavailable)
    outcome = service.generate_recommendations(run_id="NEW")
    assert outcome["status"] == "COMPLETED"
    assert len(saved) == 2
    for row in saved:
        assert row["decision"].action == "KEEP"
        assert row["decision"].reason_code == "KEEP_INSUFFICIENT_COMMON_WINDOW"
        assert row["policy"]["comparison"]["status"] == "INSUFFICIENT_DATA"
        assert row["decision"].recommended_candidate_id.startswith("OLD_")

    prior = {row["decision"].horizon: row for row in saved}
    saved.clear()
    def completed(**kwargs):
        horizon = kwargs["champion"].horizon
        ranked = [replace(c, mae=.25) for c in current[horizon]]
        decision = replace(
            prior[horizon]["decision"], action="PROMOTE", guardrail_pass=True,
            recommended_candidate_id=ranked[0].candidate_id,
            reason_code="PROMOTE_BEST_CANDIDATE", improvement_pct=87.5,
        )
        return bt.BacktestResult(decision, ranked, {"status": "COMPLETED", "version": bt.BACKTEST_VERSION})
    monkeypatch.setattr(service, "backtest_recommendation", completed)
    outcome = service.generate_recommendations(run_id="NEW")
    assert len(saved) == 2
    assert all(row["ranked_candidates"][0].mae == .25 for row in saved)
    assert all(row["decision"].action == "PROMOTE" for row in saved)
    assert all(row["policy"]["comparison"]["status"] == "COMPLETED" for row in saved)
    assert outcome["rankings"]["1"][0]["mae"] == .25

    # A changed Production slot aborts publication before the first write.
    saved.clear()
    monkeypatch.setattr(Repo, "active_production_candidate_id", lambda self, horizon, for_update=False:
                        "CHANGED" if for_update else champions[horizon].candidate_id)
    with pytest.raises(RuntimeError, match="champion changed"):
        service.generate_recommendations(run_id="NEW")
    assert saved == []


def test_existing_recommendations_are_returned_without_recomputing(monkeypatch):
    from src.recommendation import service
    class Engine:
        @contextmanager
        def connect(self):
            yield object()
    repo = SimpleNamespace(
        get_training_run=lambda run_id: {"run_id": run_id, "status": "COMPLETED", "business_date": date(2026, 6, 30)},
        get_existing_recommendation=lambda run_id, horizon: {"horizon": horizon, "policy": {"legacy": True}},
    )
    monkeypatch.setattr(service, "create_sql_engine", Engine)
    monkeypatch.setattr(service, "RecommendationRepository", lambda conn: repo)
    monkeypatch.setattr(service, "backtest_recommendation", lambda **kwargs: pytest.fail("Must not recompute history"))
    result = service.generate_recommendations(run_id="OLD")
    assert result["status"] == "ALREADY_RECOMMENDED"
    assert result["recommendations"][0]["policy"] == {"legacy": True}


def test_lstm_backtest_preserves_epoch_categories_and_time_cutoff(monkeypatch):
    frame = samples(horizon=3)
    history = []
    for day in pd.date_range("2026-04-25", "2026-08-31"):
        for department in (343, 344):
            row = {name: 1.0 for name in FEATURE_VALUE_COLUMNS}
            row.update(origin_date=day.date(), department_id=department)
            history.append(row)
    window = bt.plan_windows(SPLIT, horizon=3, configuration_known_through=SPLIT.validation_end).folds[0]
    calls = []
    def replay(**kwargs):
        calls.append(kwargs)
        parts = split_by_target_date(kwargs["sequence_frame"], kwargs["split_spec"])
        assert parts.development.target_date.max() == window.fit_end
        assert all(sequence.shape == (3, 12) for sequence in parts.train.sequence)
        return parts.test, np.full(len(parts.test), 49.0)
    monkeypatch.setattr(bt, "replay_lstm_evaluation", replay)
    c = candidate("LSTM", family="LSTM", horizon=3)
    details = details_for(c)[c.candidate_id]
    details["best_params"] = {"units": 16, "dropout": 0.0}
    rows = bt._score_block(details=details, frame=frame, feature_history=history,
                           split=SPLIT, window=window, seed=42)
    assert rows.target_date.min() == window.start
    assert calls[0]["best_epoch"] == 1
    assert calls[0]["random_seed"] == 42
    details["model_metadata"]["department_categories"] = [343]
    with pytest.raises(bt.InsufficientComparisonData, match="danh sách khoa"):
        bt._score_block(details=details, frame=frame, feature_history=history,
                         split=SPLIT, window=window, seed=42)
    assert len(calls) == 1
