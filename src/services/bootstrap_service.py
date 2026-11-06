from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import uuid

from src.bootstrap.excel_source import load_excel_bootstrap
from src.db.engine import create_sql_engine
from src.db.repositories.core import CoreRepository
from src.quality.rules import validate_rows, has_error, severity_counts


def bootstrap_excel_to_sql(excel_paths: list[str | Path]) -> dict:
    batch = load_excel_bootstrap(excel_paths)
    run_id = f"BOOT_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8].upper()}"
    source_ref = ";".join(batch.source_files)
    issues = validate_rows(batch.rows, schema_passed=True)
    counts = severity_counts(issues)

    engine = create_sql_engine()
    with engine.begin() as conn:
        repo = CoreRepository(conn)
        repo.create_pipeline_run(run_id, "EXCEL_BOOTSTRAP", source_ref, batch.data_version)
        repo.upsert_departments(batch.rows)
        raw_stats = repo.upsert_raw(batch.rows, run_id)
        repo.replace_issues_for_run(run_id, issues)

        if has_error(issues):
            repo.finish_pipeline_run(run_id, "FAILED", len(batch.rows), counts, "Data Quality ERROR; CLEAN was not built.")
            return {
                "run_id": run_id,
                "status": "FAILED",
                "data_version": batch.data_version,
                "rows": len(batch.rows),
                "raw": raw_stats,
                "quality": counts,
            }

        issue_by_key = defaultdict(list)
        for issue in issues:
            if issue.business_date is not None and issue.department_id is not None:
                issue_by_key[(issue.business_date, issue.department_id)].append(issue)
        repo.upsert_clean(batch.rows, run_id, issue_by_key)
        repo.finish_pipeline_run(run_id, "BOOTSTRAP_COMPLETED", len(batch.rows), counts)

    return {
        "run_id": run_id,
        "status": "BOOTSTRAP_COMPLETED",
        "data_version": batch.data_version,
        "rows": len(batch.rows),
        "raw": raw_stats,
        "quality": counts,
    }
