from pathlib import Path


def test_training_job_migration_has_persistent_status_and_lineage_contract():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "migrations" / "008_api_training_jobs.sql").read_text(
        encoding="utf-8"
    )

    assert "dbo.api_training_jobs" in sql
    assert "source_pipeline_run_id" in sql
    assert "training_run_id" in sql
    assert "'PENDING','RUNNING','COMPLETED','FAILED'" in sql
    assert "FK_api_training_jobs_pipeline_run" in sql
    assert "FK_api_training_jobs_training_run" in sql


def test_training_job_heartbeat_migration_adds_internal_lease_timestamp():
    root = Path(__file__).resolve().parents[1]
    migration = root / "migrations" / "011_training_job_heartbeat_recovery.sql"

    # RED until migration 011 is deliberately added.
    assert migration.is_file(), (
        "Missing migration 011_training_job_heartbeat_recovery.sql"
    )

    sql = migration.read_text(encoding="utf-8")
    normalized = " ".join(sql.lower().split())

    assert "dbo.api_training_jobs" in normalized
    assert "heartbeat_at" in normalized

    # Migration must be additive/idempotent for an existing V2 database.
    assert (
        "col_length('dbo.api_training_jobs', 'heartbeat_at') is null"
        in normalized
    )
    assert "alter table dbo.api_training_jobs" in normalized
    assert "add heartbeat_at datetime2(3) null" in normalized
