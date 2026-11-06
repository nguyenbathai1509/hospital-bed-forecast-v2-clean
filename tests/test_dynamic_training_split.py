from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.evaluation.service import (
    _expected_test_department_counts,
    _prediction_rows,
    temporal_split_from_stored,
)
from src.features.builder import FEATURE_VALUE_COLUMNS
from src.training.config import SPLIT_SPEC, TemporalSplitSpec
from src.training.data import split_by_target_date
from src.training import service, tabular
from src.evaluation.repository import EvaluationRepository


def sample_frame(end="2026-08-31", days=100):
    rows = []
    for target in pd.date_range(end=end, periods=days, freq="D"):
        for department in (343, 344):
            row = {column: 1.0 for column in FEATURE_VALUE_COLUMNS}
            row.update(
                department_id=department,
                origin_date=target.date() - timedelta(days=1),
                target_date=target.date(),
                target_occupied_beds=float(40 + target.day % 5),
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_original_dataset_keeps_exact_historical_windows():
    assert TemporalSplitSpec.ending_at(date(2026, 6, 30)) == SPLIT_SPEC


@pytest.mark.parametrize("end", [date(2026, 7, 31), date(2027, 1, 15), date(2028, 3, 15)])
def test_windows_follow_mature_data_across_month_year_and_leap_boundaries(end):
    spec = TemporalSplitSpec.ending_at(end)
    frame = sample_frame(end=end)
    parts = split_by_target_date(frame, spec)
    assert len(parts.train) == 35 * 2
    assert len(parts.validation) == 28 * 2
    assert len(parts.test) == 37 * 2
    assert parts.test.target_date.max() == end
    assert parts.train.target_date.max() < parts.validation.target_date.min()
    assert parts.validation.target_date.max() < parts.test.target_date.min()
    assert pd.concat([parts.train, parts.validation, parts.test]).target_date.tolist() == frame.target_date.tolist()
    assert temporal_split_from_stored(spec.as_dict()) == spec


@pytest.mark.parametrize("days", [0, -1, 1.5, True])
def test_invalid_window_lengths_rejected(days):
    with pytest.raises(ValueError, match="positive integer"):
        TemporalSplitSpec.ending_at(date(2026, 7, 1), test_days=days)


def test_overlapping_or_gapped_stored_windows_rejected():
    stored = SPLIT_SPEC.as_dict()
    stored["train_end"] = stored["validation_start"]
    with pytest.raises(ValueError, match="non-overlapping"):
        temporal_split_from_stored(stored)
    stored = SPLIT_SPEC.as_dict()
    stored["validation_start"] = "2026-04-29"
    with pytest.raises(ValueError, match="contiguous"):
        temporal_split_from_stored(stored)


def test_insufficient_history_and_missing_dates_fail_clearly():
    with pytest.raises(ValueError, match="non-empty"):
        split_by_target_date(sample_frame(days=50), TemporalSplitSpec.ending_at(date(2026, 8, 31)))
    frame = sample_frame()
    frame.loc[0, "target_date"] = None
    with pytest.raises(ValueError, match="missing dates"):
        split_by_target_date(frame, TemporalSplitSpec.ending_at(date(2026, 8, 31)))


def test_replay_uses_stored_window_length_and_detects_missing_or_duplicate_days():
    frame = sample_frame()
    spec = TemporalSplitSpec.ending_at(date(2026, 8, 31), test_days=30)
    counts = _expected_test_department_counts(sample_rows=frame.to_dict("records"), split_spec=spec)
    assert counts == {343: 30, 344: 30}
    test_frame = split_by_target_date(frame, spec).test
    candidate = dict(candidate_id="TEST_RF", horizon=1, model_family="RF", feature_version="v2.0", mae=0)
    rows, summary = _prediction_rows(
        test_frame=test_frame,
        predictions=test_frame.target_occupied_beds.to_numpy(),
        candidate=candidate,
        run_id="TEST",
        expected_department_counts=counts,
    )
    assert len(rows) == summary.row_count == 60
    assert summary.replay_mae == 0
    with pytest.raises(RuntimeError, match="department coverage"):
        _expected_test_department_counts(sample_rows=frame.iloc[:-1].to_dict("records"), split_spec=spec)
    duplicate = pd.concat([frame, frame.tail(1)])
    with pytest.raises(RuntimeError, match="Duplicate"):
        _expected_test_department_counts(sample_rows=duplicate.to_dict("records"), split_spec=spec)


def test_small_rf_trains_and_replays_new_dates_with_identical_metrics(monkeypatch, tmp_path):
    params = dict(n_estimators=3, max_depth=2, min_samples_leaf=1, max_features=1.0)
    monkeypatch.setattr(tabular, "_grid_for", lambda family: {key: [value] for key, value in params.items()})
    frame = sample_frame()
    spec = TemporalSplitSpec.ending_at(date(2026, 8, 31))
    result = tabular.train_tabular_candidate(
        frame=frame, model_family="RF", horizon=1,
        artifact_file=tmp_path / "rf.joblib", random_seed=42,
    )
    test_frame, predictions = tabular.replay_tabular_evaluation(
        frame=frame, model_family="RF", best_params=result.best_params,
        random_seed=42, split_spec=temporal_split_from_stored(spec.as_dict()),
    )
    assert result.evaluation_fit_rows == (100 - 37) * 2
    assert result.artifact_refit_rows == len(frame)
    assert result.overall_metrics["mae"] == pytest.approx(
        np.abs(test_frame.target_occupied_beds.to_numpy() - predictions).mean()
    )
    assert (tmp_path / "rf.joblib").is_file()


def test_training_service_persists_and_passes_one_split_to_all_eight_models(monkeypatch, tmp_path):
    frame = sample_frame()
    created, registered, calls = [], [], []

    class Engine:
        @contextmanager
        def connect(self):
            yield object()
        begin = connect

    class Repo:
        def __init__(self, conn):
            pass
        def latest_data_ready_context(self):
            return dict(business_date=date(2026, 8, 31), data_version="test")
        def completed_run_for_business_date(self, day):
            return None
        def fetch_tabular_dataset(self, horizon, version):
            return frame.to_dict("records")
        def fetch_ml_samples(self, horizon, version):
            return frame.to_dict("records")
        def fetch_feature_history(self, version):
            return frame.to_dict("records")
        def create_training_run(self, **kwargs):
            created.append(kwargs)
        def insert_candidate(self, **kwargs):
            registered.append(kwargs)
        def finish_training_run(self, run_id, **kwargs):
            assert kwargs["status"] == "COMPLETED"

    def trainer(**kwargs):
        calls.append(kwargs["split_spec"])
        return SimpleNamespace(
            validation_mae=1, evaluation_fit_rows=126, artifact_refit_rows=200,
            best_epoch=1, best_params={}, department_categories=(343, 344),
            artifact_path=str(tmp_path / "mock-artifact"), artifact_sha256="mock",
            overall_metrics={"mae": 1}, department_metrics={},
        )

    monkeypatch.setattr(service, "create_sql_engine", Engine)
    monkeypatch.setattr(service, "TrainingRepository", Repo)
    monkeypatch.setattr(service, "capture_environment", lambda: {})
    monkeypatch.setattr(service, "capture_code_revision", lambda path: "test")
    monkeypatch.setattr(service, "build_sequence_frame", lambda **kwargs: frame)
    monkeypatch.setattr(service, "train_tabular_candidate", trainer)
    monkeypatch.setattr(service, "train_lstm_candidate", trainer)
    result = service.run_training(artifact_root=tmp_path)
    expected = TemporalSplitSpec.ending_at(date(2026, 8, 31))
    assert result["status"] == "COMPLETED"
    assert calls == [expected] * 8
    assert created[0]["split_spec"] == expected.as_dict()
    assert len(registered) == 8
    assert all(row["model_metadata"]["split_spec"] == expected.as_dict() for row in registered)

    # Preflight must fail before creating another run or invoking a trainer.
    frame = sample_frame(days=50)
    with pytest.raises(ValueError, match="Cannot train H\\+1"):
        service.run_training(artifact_root=tmp_path)
    assert len(created) == 1
    assert len(calls) == 8


@pytest.mark.parametrize("departments,test_days", [(2, 37), (3, 30), (1, 14)])
def test_completion_counts_follow_each_registered_candidate_and_department(departments, test_days):
    expected = [
        dict(candidate_id=f"H{h}_{f}", horizon=h, model_family=f, department_id=d, sample_count=test_days)
        for h in (1, 3) for f in ("RF", "XGBOOST", "SVR", "LSTM") for d in range(departments)
    ]
    actual = [
        dict(candidate_id=row["candidate_id"], department_id=row["department_id"], row_count=test_days)
        for row in expected
    ]

    class Connection:
        def execute(self, statement, params):
            assert params == {"run_id": "TEST"}
            rows = actual if "model_evaluation_predictions" in str(statement) else expected
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    repo = EvaluationRepository(Connection())
    assert repo.evaluation_evidence_complete("TEST")
    # Total unchanged, but evidence is misplaced across groups: must not reuse.
    actual[0]["row_count"] -= 1
    actual[1]["row_count"] += 1
    assert not repo.evaluation_evidence_complete("TEST")
    actual[0]["row_count"] += 1
    actual[1]["row_count"] -= 1
    actual.pop()
    assert not repo.evaluation_evidence_complete("TEST")
    actual.clear()
    assert not repo.evaluation_evidence_complete("TEST")


def test_partial_stored_replay_is_rejected_without_rewriting(monkeypatch):
    from src.evaluation import service as evaluation

    class Engine:
        @contextmanager
        def connect(self):
            yield object()

    repo = SimpleNamespace(
        training_run=lambda run_id: {"status": "COMPLETED"},
        prediction_count=lambda run_id: 10,
        evaluation_evidence_complete=lambda run_id: False,
    )
    monkeypatch.setattr(evaluation, "create_sql_engine", Engine)
    monkeypatch.setattr(evaluation, "EvaluationRepository", lambda conn: repo)
    with pytest.raises(RuntimeError, match="incomplete or inconsistent"):
        evaluation.replay_training_evaluation("TEST")


def test_lstm_uses_supplied_window_for_tuning_evaluation_and_bundle(monkeypatch, tmp_path):
    import json
    from src.training import lstm

    frame = sample_frame(days=12)
    frame["sequence"] = [np.full((3, 12), float(i)) for i in range(len(frame))]
    spec = TemporalSplitSpec.ending_at(date(2026, 8, 31), validation_days=3, test_days=4)
    fits = []

    class Model:
        def fit(self, x, y, **kwargs):
            fits.append((len(x), kwargs))
            return SimpleNamespace(history={"val_mae": [1.0]}, epoch=[0])
        def predict(self, x, **kwargs):
            return np.zeros((len(x), 1))
        def save(self, path):
            path.write_bytes(b"test model")

    fake_tf = SimpleNamespace(keras=SimpleNamespace(callbacks=SimpleNamespace(EarlyStopping=lambda **kwargs: None)))
    monkeypatch.setattr(lstm, "_require_tensorflow", lambda: fake_tf)
    monkeypatch.setattr(lstm, "_build_model", lambda *args, **kwargs: Model())
    monkeypatch.setattr(lstm, "LSTM_GRID", {"units": [16], "dropout": [0.0]})
    result = lstm.train_lstm_candidate(
        sequence_frame=frame, horizon=1, artifact_dir=tmp_path / "bundle",
        random_seed=42, department_categories=(343, 344), split_spec=spec,
    )
    assert [count for count, _ in fits] == [10, 16, 24]
    assert all(kwargs["shuffle"] is False for _, kwargs in fits)
    assert result.overall_metrics["sample_count"] == 8
    metadata = json.loads((tmp_path / "bundle" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["split_spec"] == spec.as_dict()
