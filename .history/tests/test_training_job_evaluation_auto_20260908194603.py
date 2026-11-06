from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

import src.api.training_jobs as training_jobs


RUN_ID = "TRN_TEST"
OLD_JOB_ID = "TJOB_OLD"
NEW_JOB_ID = "TJOB_NEW"


class _FakeEngine:
    @contextmanager
    def begin(self):
        yield object()


class _StartRepo:
    def __init__(self, *, evidence_count: int):
        self.evidence_count = evidence_count
        self.inserted = []

    def latest_data_ready_context(self):
        return {
            "run_id": "DAY_TEST",
            "business_date": date(2026, 6, 30),
            "data_version": "data-test",
            "completed_at": None,
        }

    def reusable_job_for_business_date(self, business_date):
        assert business_date == date(2026, 6, 30)
        return {
            "job_id": OLD_JOB_ID,
            "business_date": business_date,
            "source_pipeline_run_id": "DAY_TEST",
            "status": "COMPLETED",
            "requested_by": "api",
            "random_seed": 42,
            "training_run_id": RUN_ID,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
        }

    def evaluation_prediction_count(self, training_run_id: str) -> int:
        assert training_run_id == RUN_ID
        return self.evidence_count

    def insert_pending_job(self, **kwargs):
        self.inserted.append(kwargs)


def test_training_workflow_auto_runs_evaluation_replay(monkeypatch):
    calls = []

    def fake_training(*, triggered_by, random_seed):
        calls.append(("training", triggered_by, random_seed))
        return {
            "status": "ALREADY_COMPLETED",
            "run_id": RUN_ID,
        }

    def fake_recommendation(*, run_id):
        calls.append(("recommendation", run_id))
        return {
            "status": "ALREADY_RECOMMENDED",
            "run_id": run_id,
        }

    def fake_evaluation(run_id):
        calls.append(("evaluation", run_id))
        return {
            "status": "COMPLETED",
            "run_id": run_id,
            "prediction_count": 592,
        }

    monkeypatch.setattr(training_jobs, "run_training", fake_training)
    monkeypatch.setattr(
        training_jobs,
        "generate_recommendations",
        fake_recommendation,
    )
    monkeypatch.setattr(
        training_jobs,
        "replay_training_evaluation",
        fake_evaluation,
    )

    run_id, result = training_jobs._execute_training_workflow(
        requested_by="operator",
        random_seed=42,
    )

    assert run_id == RUN_ID
    assert result["training"]["status"] == "ALREADY_COMPLETED"
    assert result["recommendation"]["status"] == "ALREADY_RECOMMENDED"
    assert result["evaluation"]["status"] == "COMPLETED"
    assert result["evaluation"]["prediction_count"] == 592
    assert calls == [
        ("training", "api:operator", 42),
        ("recommendation", RUN_ID),
        ("evaluation", RUN_ID),
    ]


def test_training_workflow_fails_job_stage_when_evaluation_fails(monkeypatch):
    monkeypatch.setattr(
        training_jobs,
        "run_training",
        lambda **kwargs: {
            "status": "ALREADY_COMPLETED",
            "run_id": RUN_ID,
        },
    )
    monkeypatch.setattr(
        training_jobs,
        "generate_recommendations",
        lambda **kwargs: {
            "status": "ALREADY_RECOMMENDED",
            "run_id": RUN_ID,
        },
    )

    def fail_replay(run_id):
        raise RuntimeError("evaluation metric mismatch")

    monkeypatch.setattr(
        training_jobs,
        "replay_training_evaluation",
        fail_replay,
    )

    with pytest.raises(RuntimeError, match="evaluation metric mismatch"):
        training_jobs._execute_training_workflow(
            requested_by="operator",
            random_seed=42,
        )


def test_completed_legacy_job_without_evaluation_is_not_reused(monkeypatch):
    repo = _StartRepo(evidence_count=0)

    monkeypatch.setattr(
        training_jobs,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )
    monkeypatch.setattr(
        training_jobs,
        "TrainingJobRepository",
        lambda conn: repo,
    )
    monkeypatch.setattr(
        training_jobs,
        "_new_job_id",
        lambda: NEW_JOB_ID,
    )

    result = training_jobs.TrainingJobService().start_job(
        requested_by="operator",
        random_seed=42,
    )

    assert result["job_id"] == NEW_JOB_ID
    assert result["status"] == "PENDING"
    assert result["reused"] is False
    assert result["should_schedule"] is True
    assert len(repo.inserted) == 1


def test_completed_job_with_full_evaluation_is_reused(monkeypatch):
    repo = _StartRepo(
        evidence_count=training_jobs.EXPECTED_TOTAL_REPLAY_ROWS
    )

    monkeypatch.setattr(
        training_jobs,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )
    monkeypatch.setattr(
        training_jobs,
        "TrainingJobRepository",
        lambda conn: repo,
    )

    result = training_jobs.TrainingJobService().start_job(
        requested_by="operator",
        random_seed=42,
    )

    assert result["job_id"] == OLD_JOB_ID
    assert result["status"] == "COMPLETED"
    assert result["reused"] is True
    assert result["should_schedule"] is False
    assert repo.inserted == []