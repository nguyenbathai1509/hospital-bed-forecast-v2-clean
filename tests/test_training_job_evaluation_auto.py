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
    def recover_stale_running_jobs(self, *, stale_after_seconds):
        return []

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

    def evaluation_evidence_complete(self, training_run_id: str) -> bool:
        assert training_run_id == RUN_ID
        return self.evidence_count == 592

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
        evidence_count=592
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



class _HeartbeatSqlResult:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _HeartbeatSqlConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        normalized = " ".join(str(statement).lower().split())
        self.statements.append(
            {
                "sql": normalized,
                "params": {} if params is None else dict(params),
            }
        )

        if "output inserted.job_id" in normalized:
            return _HeartbeatSqlResult(
                {
                    "job_id": "TJOB_HEARTBEAT",
                    "business_date": date(2026, 6, 30),
                    "source_pipeline_run_id": "DAY_TEST",
                    "status": "RUNNING",
                    "requested_by": "operator",
                    "random_seed": 42,
                    "training_run_id": None,
                    "created_at": None,
                    "started_at": None,
                    "completed_at": None,
                }
            )

        return _HeartbeatSqlResult()


def test_claim_job_initializes_worker_heartbeat():
    conn = _HeartbeatSqlConnection()
    repo = training_jobs.TrainingJobRepository(conn)

    claimed = repo.claim_job("TJOB_HEARTBEAT")

    assert claimed is not None
    assert len(conn.statements) == 1

    statement = conn.statements[0]

    assert statement["params"]["job_id"] == "TJOB_HEARTBEAT"
    assert "status='running'" in statement["sql"]
    assert "heartbeat_at=sysutcdatetime()" in statement["sql"]
    assert "where job_id=:job_id and status='pending'" in statement["sql"]


def test_touch_heartbeat_refreshes_only_running_job():
    conn = _HeartbeatSqlConnection()
    repo = training_jobs.TrainingJobRepository(conn)

    repo.touch_heartbeat("TJOB_HEARTBEAT")

    assert len(conn.statements) == 1

    statement = conn.statements[0]

    assert statement["params"]["job_id"] == "TJOB_HEARTBEAT"
    assert "update dbo.api_training_jobs" in statement["sql"]
    assert "set heartbeat_at=sysutcdatetime()" in statement["sql"]
    assert "where job_id=:job_id and status='running'" in statement["sql"]



class _StaleRecoveryResult:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _StaleRecoveryConnection:
    def __init__(self, stale_rows=None):
        self.stale_rows = list(stale_rows or [])
        self.statements = []

    def execute(self, statement, params=None):
        normalized = " ".join(str(statement).lower().split())

        self.statements.append(
            {
                "sql": normalized,
                "params": {} if params is None else dict(params),
            }
        )

        if (
            "update dbo.api_training_jobs" in normalized
            and "output" in normalized
        ):
            return _StaleRecoveryResult(self.stale_rows)

        return _StaleRecoveryResult()


def test_recover_stale_running_jobs_uses_heartbeat_cutoff_and_fails_linked_run():
    conn = _StaleRecoveryConnection(
        stale_rows=[
            {
                "job_id": "TJOB_STALE",
                "training_run_id": "TRN_STALE",
            }
        ]
    )

    repo = training_jobs.TrainingJobRepository(conn)

    recovered = repo.recover_stale_running_jobs(
        stale_after_seconds=90,
    )

    assert recovered == [
        {
            "job_id": "TJOB_STALE",
            "training_run_id": "TRN_STALE",
        }
    ]

    assert len(conn.statements) == 2

    job_update = conn.statements[0]

    assert job_update["params"]["stale_after_seconds"] == 90
    assert "update dbo.api_training_jobs" in job_update["sql"]
    assert "status='failed'" in job_update["sql"]
    assert "completed_at=sysutcdatetime()" in job_update["sql"]
    assert "where (status='running'" in job_update["sql"]
    assert "or (status='pending' and created_at" in job_update["sql"]

    # Fresh heartbeat must not be recovered. started_at is the fallback for
    # RUNNING rows created before heartbeat support existed.
    canonical_job_sql = (
        job_update["sql"]
        .replace("( ", "(")
        .replace(" )", ")")
    )

    assert (
        "coalesce(heartbeat_at, started_at) "
        "< dateadd(second, -:stale_after_seconds, sysutcdatetime())"
        in canonical_job_sql
    )

    run_update = conn.statements[1]

    assert run_update["params"]["training_run_id"] == "TRN_STALE"
    assert "update dbo.training_runs" in run_update["sql"]
    assert "status='failed'" in run_update["sql"]
    assert "completed_at=sysutcdatetime()" in run_update["sql"]
    assert (
        "where run_id=:training_run_id and status='running'"
        in run_update["sql"]
    )


def test_recover_stale_running_jobs_with_no_matches_does_not_touch_training_runs():
    conn = _StaleRecoveryConnection(stale_rows=[])

    repo = training_jobs.TrainingJobRepository(conn)

    recovered = repo.recover_stale_running_jobs(
        stale_after_seconds=90,
    )

    assert recovered == []

    # Only the guarded stale-job UPDATE is allowed. No scientific Training Run
    # may be modified when no stale API job was actually recovered.
    assert len(conn.statements) == 1
    assert "update dbo.api_training_jobs" in conn.statements[0]["sql"]
    assert "update dbo.training_runs" not in conn.statements[0]["sql"]



class _RecoveryOrderStartRepo:
    def __init__(self):
        self.calls = []
        self.inserted = []
        self.stale_recovered = False

    def latest_data_ready_context(self):
        self.calls.append("ready")
        return {
            "run_id": "DAY_TEST",
            "business_date": date(2026, 6, 30),
            "data_version": "data-test",
            "completed_at": None,
        }

    def recover_stale_running_jobs(self, *, stale_after_seconds: int):
        self.calls.append("recover")

        assert isinstance(stale_after_seconds, int)
        assert stale_after_seconds > 0

        self.stale_recovered = True

        return [
            {
                "job_id": "TJOB_STALE",
                "training_run_id": "TRN_STALE",
            }
        ]

    def reusable_job_for_business_date(self, business_date):
        self.calls.append("reuse")

        assert business_date == date(2026, 6, 30)

        # Critical ordering guarantee:
        # reuse lookup must happen only after stale recovery.
        assert self.stale_recovered is True

        return None

    def insert_pending_job(self, **kwargs):
        self.calls.append("insert")
        self.inserted.append(kwargs)


def test_start_job_recovers_stale_jobs_before_reuse_lookup(monkeypatch):
    repo = _RecoveryOrderStartRepo()

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
        lambda: "TJOB_AFTER_STALE",
    )

    result = training_jobs.TrainingJobService().start_job(
        requested_by="operator",
        random_seed=42,
    )

    assert repo.calls == [
        "ready",
        "recover",
        "reuse",
        "insert",
    ]

    assert result["job_id"] == "TJOB_AFTER_STALE"
    assert result["status"] == "PENDING"
    assert result["reused"] is False
    assert result["should_schedule"] is True

    assert len(repo.inserted) == 1



def test_training_job_heartbeat_timing_has_safe_stale_margin():
    interval = training_jobs.TRAINING_JOB_HEARTBEAT_INTERVAL_SECONDS
    stale_after = training_jobs.TRAINING_JOB_STALE_AFTER_SECONDS

    assert isinstance(interval, int)
    assert isinstance(stale_after, int)
    assert interval > 0

    # A worker must be allowed to miss several heartbeat opportunities
    # before another start request can classify it as stale.
    assert stale_after >= interval * 4


class _ScriptedHeartbeatStopEvent:
    def __init__(self, responses):
        self.responses = list(responses)
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)

        if not self.responses:
            raise AssertionError(
                "heartbeat loop waited more times than expected"
            )

        return self.responses.pop(0)


class _HeartbeatLoopEngine:
    def __init__(self):
        self.begin_count = 0

    @contextmanager
    def begin(self):
        self.begin_count += 1
        yield object()


class _HeartbeatLoopRepo:
    def __init__(self):
        self.touched = []

    def touch_heartbeat(self, job_id):
        self.touched.append(job_id)


def test_heartbeat_loop_refreshes_with_fresh_transaction_each_tick(
    monkeypatch,
):
    engine = _HeartbeatLoopEngine()
    repo = _HeartbeatLoopRepo()

    monkeypatch.setattr(
        training_jobs,
        "TrainingJobRepository",
        lambda conn: repo,
    )

    stop_event = _ScriptedHeartbeatStopEvent(
        [
            False,
            False,
            True,
        ]
    )

    training_jobs._heartbeat_loop(
        engine=engine,
        job_id="TJOB_HEARTBEAT",
        stop_event=stop_event,
        interval_seconds=15,
    )

    assert stop_event.waits == [
        15,
        15,
        15,
    ]

    assert repo.touched == [
        "TJOB_HEARTBEAT",
        "TJOB_HEARTBEAT",
    ]

    # Each heartbeat gets its own transaction/connection scope.
    assert engine.begin_count == 2
