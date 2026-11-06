from contextlib import contextmanager
from pathlib import Path
from threading import Event, RLock, Thread
from types import SimpleNamespace
import ast
import os

import pytest

import src.api.training_jobs as jobs
from src.training.job_context import (
    TrainingJobLeaseLost, fence_training_job, link_training_run, training_job_context,
)


class MemoryConnection:
    def __init__(self):
        self.status = "PENDING"
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((str(sql), params))
        return self

    def scalar_one_or_none(self):
        return self.status


class MemoryEngine:
    def __init__(self):
        self.conn = MemoryConnection()
        self.lock = RLock()

    @contextmanager
    def begin(self):
        with self.lock:
            yield self.conn


class MemoryRepo:
    def __init__(self, conn):
        self.conn = conn

    def claim_job(self, job_id):
        if self.conn.status != "PENDING":
            return None
        self.conn.status = "RUNNING"
        return {"requested_by": "test", "random_seed": 42}

    def touch_heartbeat(self, job_id):
        return self.conn.status == "RUNNING"

    def finish_completed(self, **kwargs):
        assert self.conn.status == "RUNNING"
        self.conn.status = "COMPLETED"

    def finish_failed(self, **kwargs):
        if self.conn.status == "RUNNING":
            self.conn.status = "FAILED"


@pytest.mark.parametrize("outcome", ["success", "error", "lost", "late_success", "db_error"])
def test_worker_starts_and_stops_heartbeat_and_never_revives_lost_job(monkeypatch, caplog, outcome):
    engine = MemoryEngine()
    entered, exited = Event(), Event()

    def heartbeat(**kwargs):
        entered.set()
        try:
            assert kwargs["stop_event"].wait(3)
        finally:
            exited.set()

    def workflow(**kwargs):
        assert entered.wait(2)
        assert kwargs["job_id"] == "TJOB_TEST"
        if outcome in {"lost", "late_success"}:
            engine.conn.status = "FAILED"
        if outcome == "error":
            raise ValueError("simulated fit failure")
        if outcome == "db_error":
            raise ConnectionError("simulated database outage")
        if outcome == "lost":
            fence_training_job(engine.conn)
        return "RUN_TEST", {"ok": True}

    monkeypatch.setattr(jobs, "create_sql_engine", lambda: engine)
    monkeypatch.setattr(jobs, "TrainingJobRepository", MemoryRepo)
    monkeypatch.setattr(jobs, "_heartbeat_loop", heartbeat)
    monkeypatch.setattr(jobs, "_execute_training_workflow", workflow)
    jobs.TrainingJobService().run_job("TJOB_TEST")
    assert entered.is_set() and exited.is_set()
    assert engine.conn.status == ("COMPLETED" if outcome == "success" else "FAILED")
    # Context must not leak into later CLI work, even on exceptions.
    fence_training_job(object())
    if outcome in {"lost", "late_success"}:
        assert "lease loss" in caplog.text
    if outcome in {"error", "db_error"}:
        assert "Worker failed" in caplog.text


def test_duplicate_worker_does_not_start_work_or_heartbeat(monkeypatch):
    engine = MemoryEngine()
    engine.conn.status = "RUNNING"
    monkeypatch.setattr(jobs, "create_sql_engine", lambda: engine)
    monkeypatch.setattr(jobs, "TrainingJobRepository", MemoryRepo)
    monkeypatch.setattr(jobs, "Thread", lambda **kw: pytest.fail("duplicate worker"))
    jobs.TrainingJobService().run_job("TJOB_TEST")


def test_heartbeat_recovers_after_transient_database_failure(monkeypatch, caplog):
    calls = []

    class Repo:
        def touch_heartbeat(self, job_id):
            calls.append(job_id)
            if len(calls) == 1:
                raise ConnectionError("transient")
            return False  # Recovery has now revoked ownership: stop the loop.

    class Stop:
        def wait(self, interval):
            assert len(calls) < 2
            return False

    monkeypatch.setattr(jobs, "TrainingJobRepository", lambda conn: Repo())
    jobs._heartbeat_loop(engine=MemoryEngine(), job_id="TJOB_TEST", stop_event=Stop(), interval_seconds=15)
    assert len(calls) == 2
    assert "heartbeat refresh failed" in caplog.text
    assert "no longer active" in caplog.text


@pytest.mark.parametrize("status", ["FAILED", "COMPLETED", "PENDING", None])
def test_write_fence_rejects_non_running_job(status):
    conn = MemoryConnection()
    conn.status = status
    with training_job_context("TJOB_OLD"), pytest.raises(TrainingJobLeaseLost):
        fence_training_job(conn)
    sql, params = conn.statements[0]
    assert "UPDLOCK, HOLDLOCK" in sql
    assert params == {"job_id": "TJOB_OLD"}


def test_fence_serializes_publication_with_recovery():
    # Deterministic lock interleaving; SQL Server lock syntax is checked separately.
    engine = MemoryEngine()
    engine.conn.status = "RUNNING"
    recovering, recovered = Event(), Event()

    def recover():
        recovering.set()
        with engine.begin() as conn:
            conn.status = "FAILED"
        recovered.set()

    with training_job_context("TJOB_OLD"):
        with engine.begin() as conn:
            fence_training_job(conn)
            thread = Thread(target=recover)
            thread.start()
            assert recovering.wait(2)
            assert not recovered.is_set()
            link_training_run(conn, "RUN_OLD")
        thread.join(timeout=2)
        assert recovered.is_set()
        with engine.begin() as conn, pytest.raises(TrainingJobLeaseLost):
            fence_training_job(conn)


@pytest.mark.parametrize("lost_after", ["training", "recommendation"])
def test_workflow_does_not_enter_next_stage_after_lease_loss(monkeypatch, lost_after):
    engine = MemoryEngine()
    engine.conn.status = "RUNNING"
    stages = []

    def stage(name):
        stages.append(name)
        if name == lost_after:
            engine.conn.status = "FAILED"
        return {"status": "COMPLETED", "run_id": "RUN_TEST"}

    monkeypatch.setattr(jobs, "run_training", lambda **kw: stage("training"))
    monkeypatch.setattr(jobs, "generate_recommendations", lambda **kw: stage("recommendation"))
    monkeypatch.setattr(jobs, "replay_training_evaluation", lambda *a: pytest.fail("late evaluation"))
    with training_job_context("TJOB_TEST"), pytest.raises(TrainingJobLeaseLost):
        jobs._execute_training_workflow(requested_by="test", random_seed=42, job_id="TJOB_TEST", engine=engine)
    assert stages == (["training"] if lost_after == "training" else ["training", "recommendation"])


def test_training_losing_lease_during_fit_cannot_register_or_complete(monkeypatch, tmp_path):
    import pandas as pd
    from src.training import service

    engine = MemoryEngine()
    engine.connect = engine.begin
    engine.conn.status = "RUNNING"
    dates = pd.date_range("2026-06-01", "2026-08-31")
    rows = [dict(origin_date=d.date(), target_date=d.date(), department_id=343) for d in dates]
    created = []
    repo = SimpleNamespace(
        latest_data_ready_context=lambda: {"business_date": dates[-1].date(), "data_version": "test"},
        completed_run_for_business_date=lambda day: None,
        fetch_tabular_dataset=lambda *a: rows,
        fetch_ml_samples=lambda *a: rows,
        fetch_feature_history=lambda *a: rows,
        create_training_run=lambda **kw: created.append(kw),
        insert_candidate=lambda **kw: pytest.fail("late candidate write"),
        finish_training_run=lambda *a, **kw: pytest.fail("late run status write"),
    )

    def fit(**kwargs):
        assert len(created) == 1
        assert any("SET training_run_id=:run_id" in sql for sql, _ in engine.conn.statements)
        engine.conn.status = "FAILED"  # Recovery while fit was in progress.
        return SimpleNamespace(
            validation_mae=1, evaluation_fit_rows=50, artifact_refit_rows=92,
            artifact_path=str(tmp_path / "unused.joblib"), artifact_sha256="test",
            best_params={}, overall_metrics={"mae": 1}, department_metrics={},
        )

    monkeypatch.setattr(service, "create_sql_engine", lambda: engine)
    monkeypatch.setattr(service, "TrainingRepository", lambda conn: repo)
    monkeypatch.setattr(service, "capture_environment", lambda: {})
    monkeypatch.setattr(service, "capture_code_revision", lambda path: "test")
    monkeypatch.setattr(service, "train_tabular_candidate", fit)
    with training_job_context("TJOB_TEST"), pytest.raises(TrainingJobLeaseLost):
        service.run_training(artifact_root=tmp_path)


@pytest.mark.parametrize("path, expected", [
    ("src/training/service.py", 5),
    ("src/recommendation/service.py", 1),
    ("src/evaluation/service.py", 1),
])
def test_every_workflow_write_transaction_is_fenced(path, expected):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.With)
              and any(ast.unparse(item.context_expr) == "engine.begin()" for item in node.items)]
    assert len(writes) == expected
    for node in writes:
        assert ast.unparse(node.body[0]) == "fence_training_job(conn)"
    if "training/service" in path:
        creation = next(node for node in writes if "create_training_run" in ast.unparse(node))
        assert "link_training_run(conn, run_id)" in ast.unparse(creation)


def test_launcher_captures_stdout_stderr_without_overwriting_log(monkeypatch, tmp_path):
    launches = []

    def launch(command, **kwargs):
        assert "-u" in command
        assert kwargs["stderr"] == jobs.subprocess.STDOUT
        kwargs["stdout"].write(b"worker diagnostic\n")
        launches.append(command)

    monkeypatch.setattr(jobs, "TRAINING_JOB_LOG_DIR", tmp_path)
    monkeypatch.setattr(jobs.subprocess, "Popen", launch)
    jobs.TrainingJobLauncher().launch("TJOB_TEST")
    jobs.TrainingJobLauncher().launch("TJOB_TEST")
    assert (tmp_path / "TJOB_TEST.log").read_bytes() == b"worker diagnostic\n" * 2
    assert len(launches) == 2


@pytest.mark.parametrize("job_id", ["../../escape", "TJOB_../escape", "TJOB_x/y", ""])
def test_launcher_rejects_unsafe_log_paths(monkeypatch, job_id):
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        jobs.TrainingJobLauncher().launch(job_id)


@pytest.mark.skipif(os.getenv("TRAINING_SQL_TESTS") != "1", reason="Opt-in SQL Server temporary-table test")
def test_sql_server_recovery_and_late_writes_in_temporary_tables():
    """Execute real T-SQL, rewriting ALL targets to connection-local temp tables.

    No production row is read, inserted, updated or deleted by this test.
    """
    from sqlalchemy import text
    from src.db.engine import create_sql_engine

    engine = create_sql_engine()
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.exec_driver_sql("""
                    CREATE TABLE #worker_jobs (
                        job_id varchar(80) PRIMARY KEY, business_date date,
                        source_pipeline_run_id varchar(60), status varchar(20),
                        requested_by nvarchar(100), random_seed int, training_run_id varchar(60),
                        created_at datetime2, started_at datetime2, completed_at datetime2,
                        heartbeat_at datetime2, error_message nvarchar(max), result_json nvarchar(max)
                    );
                    CREATE TABLE #worker_runs (
                        run_id varchar(60) PRIMARY KEY, status varchar(20),
                        completed_at datetime2, error_message nvarchar(max)
                    );
                    INSERT INTO #worker_runs(run_id,status)
                        VALUES ('RUN_OLD','RUNNING'), ('RUN_DONE','COMPLETED');
                    INSERT INTO #worker_jobs(job_id,status,training_run_id,created_at,started_at,heartbeat_at)
                    VALUES
                      ('TJOB_OLD','RUNNING','RUN_OLD',DATEADD(second,-300,SYSUTCDATETIME()),DATEADD(second,-290,SYSUTCDATETIME()),DATEADD(second,-250,SYSUTCDATETIME())),
                      ('TJOB_FRESH','RUNNING',NULL,DATEADD(second,-300,SYSUTCDATETIME()),DATEADD(second,-290,SYSUTCDATETIME()),SYSUTCDATETIME()),
                      ('TJOB_PENDING','PENDING',NULL,DATEADD(second,-300,SYSUTCDATETIME()),NULL,NULL),
                      ('TJOB_NEW','PENDING',NULL,SYSUTCDATETIME(),NULL,NULL),
                      ('TJOB_DONE','RUNNING','RUN_DONE',DATEADD(second,-300,SYSUTCDATETIME()),DATEADD(second,-290,SYSUTCDATETIME()),NULL);
                """)

                class TempConnection:
                    def execute(self, statement, params=None):
                        sql = str(statement).replace("dbo.api_training_jobs", "#worker_jobs").replace("dbo.training_runs", "#worker_runs")
                        assert "dbo." not in sql
                        return conn.execute(text(sql), params or {})

                temporary = TempConnection()
                repo = jobs.TrainingJobRepository(temporary)
                recovered = repo.recover_stale_running_jobs(stale_after_seconds=120)
                assert {r["job_id"] for r in recovered} == {"TJOB_OLD", "TJOB_PENDING", "TJOB_DONE"}
                assert repo.touch_heartbeat("TJOB_OLD") is False
                assert repo.touch_heartbeat("TJOB_FRESH") is True
                assert repo.claim_job("TJOB_PENDING") is None
                assert repo.claim_job("TJOB_NEW") is not None
                assert repo.claim_job("TJOB_NEW") is None
                repo.finish_completed(job_id="TJOB_OLD", training_run_id="RUN_OLD", result={"late": True})
                repo.finish_failed(job_id="TJOB_OLD", error_message="late failure")
                states = {r.job_id: r.status for r in conn.execute(text("SELECT job_id,status FROM #worker_jobs"))}
                assert states["TJOB_OLD"] == "FAILED"
                assert states["TJOB_FRESH"] == "RUNNING"
                runs = {r.run_id: r.status for r in conn.execute(text("SELECT run_id,status FROM #worker_runs"))}
                assert runs == {"RUN_OLD": "FAILED", "RUN_DONE": "COMPLETED"}
                with training_job_context("TJOB_OLD"), pytest.raises(TrainingJobLeaseLost):
                    fence_training_job(temporary)
                with training_job_context("TJOB_NEW"):
                    fence_training_job(temporary)
                    link_training_run(temporary, "RUN_DONE")
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
