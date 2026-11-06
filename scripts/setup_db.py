from __future__ import annotations

from pathlib import Path
import re

from sqlalchemy import text

from src.config import settings
from src.db.engine import create_sql_engine

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"


def split_batches(sql: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?im)^\s*GO\s*$", sql) if part.strip()]


def ensure_database() -> None:
    safe_name = settings.db_name.replace("]", "]]" )
    engine = create_sql_engine(database="master")
    # SQL Server CREATE DATABASE must run outside a user transaction.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(text("SELECT DB_ID(:name)"), {"name": settings.db_name}).scalar()
        if exists is None:
            # Database identifiers cannot be bound parameters; name comes from local env and is escaped.
            conn.exec_driver_sql(f"CREATE DATABASE [{safe_name}]")
            print(f"Created database: {settings.db_name}")
        else:
            print(f"Database already exists: {settings.db_name}")


def apply_migrations() -> None:
    engine = create_sql_engine(database=settings.db_name)
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            IF OBJECT_ID('dbo.schema_migrations', 'U') IS NULL
            CREATE TABLE dbo.schema_migrations (
                migration_id VARCHAR(100) NOT NULL PRIMARY KEY,
                applied_at DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()
            )
        """)
        for path in sorted(MIGRATIONS.glob("*.sql")):
            migration_id = path.name
            applied = conn.execute(text("SELECT 1 FROM dbo.schema_migrations WHERE migration_id=:id"), {"id": migration_id}).scalar()
            if applied:
                print(f"Skip already applied: {migration_id}")
                continue
            sql = path.read_text(encoding="utf-8")
            for batch in split_batches(sql):
                conn.exec_driver_sql(batch)
            conn.execute(text("INSERT INTO dbo.schema_migrations(migration_id) VALUES (:id)"), {"id": migration_id})
            print(f"Applied: {migration_id}")


if __name__ == "__main__":
    settings.validate_for_database()
    ensure_database()
    apply_migrations()
    print("V2 database migrations complete.")
