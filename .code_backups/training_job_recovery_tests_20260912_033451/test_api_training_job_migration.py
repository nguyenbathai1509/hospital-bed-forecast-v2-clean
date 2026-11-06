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