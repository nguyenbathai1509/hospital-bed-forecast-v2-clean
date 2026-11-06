"""Apply only migration 011, with an idle-worker guard (no other migrations)."""
from pathlib import Path

from sqlalchemy import text

from scripts.setup_db import split_batches
from src.db.engine import create_sql_engine


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "migrations" / "011_training_job_heartbeat_recovery.sql"
    engine = create_sql_engine()
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCK_TIMEOUT 5000")
            active = conn.execute(text("""
                SELECT COUNT(*) FROM dbo.api_training_jobs WITH (TABLOCKX, HOLDLOCK)
                WHERE status IN ('PENDING', 'RUNNING')
            """)).scalar_one()
            if active:
                raise RuntimeError("Stop/drain existing training workers before applying migration 011")
            for batch in split_batches(path.read_text(encoding="utf-8")):
                conn.exec_driver_sql(batch)
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id=:migration_id)
                    INSERT INTO dbo.schema_migrations(migration_id) VALUES (:migration_id)
            """), {"migration_id": path.name})
        print("Migration 011 ready. No training or forecast records changed.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
