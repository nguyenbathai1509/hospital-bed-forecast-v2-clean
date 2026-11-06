from __future__ import annotations

import json
from sqlalchemy import text

from src.db.engine import create_sql_engine


def main() -> None:
    engine = create_sql_engine()
    report: dict = {}
    with engine.connect() as conn:
        report["sql_server_version"] = conn.execute(text("SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(50))")).scalar()
        report["raw_count"] = conn.execute(text("SELECT COUNT(*) FROM dbo.raw_bed_daily")).scalar()
        report["clean_count"] = conn.execute(text("SELECT COUNT(*) FROM dbo.clean_bed_daily")).scalar()
        report["raw_duplicate_business_keys"] = conn.execute(text("""
            SELECT COUNT(*) FROM (
              SELECT business_date, department_id
              FROM dbo.raw_bed_daily
              GROUP BY business_date, department_id HAVING COUNT(*) > 1
            ) d
        """)).scalar()
        report["clean_duplicate_business_keys"] = conn.execute(text("""
            SELECT COUNT(*) FROM (
              SELECT business_date, department_id
              FROM dbo.clean_bed_daily
              GROUP BY business_date, department_id HAVING COUNT(*) > 1
            ) d
        """)).scalar()
        report["departments"] = [dict(r) for r in conn.execute(text("""
            SELECT department_id, department_code, department_name, planned_beds, is_active
            FROM dbo.departments ORDER BY department_id
        """)).mappings()]
        report["ranges"] = [dict(r) for r in conn.execute(text("""
            SELECT department_id, MIN(business_date) AS min_date, MAX(business_date) AS max_date, COUNT(*) AS row_count
            FROM dbo.raw_bed_daily GROUP BY department_id ORDER BY department_id
        """)).mappings()]
        report["quality_by_rule"] = [dict(r) for r in conn.execute(text("""
            SELECT rule_id, severity, COUNT(*) AS issue_count
            FROM dbo.data_quality_issues
            WHERE pipeline_run_id=(SELECT TOP 1 run_id FROM dbo.pipeline_runs ORDER BY started_at DESC)
            GROUP BY rule_id, severity ORDER BY rule_id, severity
        """)).mappings()]
        report["balance_check_rows"] = [dict(r) for r in conn.execute(text("""
            SELECT business_date, department_id, occupied_start, admissions, transfer_in, discharges, transfer_out,
                   occupied_end, expected_occupied_end, balance_error, quality_flag
            FROM dbo.clean_bed_daily WHERE balance_error <> 0 ORDER BY business_date, department_id
        """)).mappings()]
        report["raw_revision_gt1"] = conn.execute(text("SELECT COUNT(*) FROM dbo.raw_bed_daily WHERE revision_no > 1")).scalar()
        report["latest_run"] = dict(conn.execute(text("""
            SELECT TOP 1 run_id, source_mode, status, rows_extracted,
                   quality_error_count, quality_warning_count, quality_check_count, data_version
            FROM dbo.pipeline_runs ORDER BY started_at DESC
        """)).mappings().one())

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    errors = []
    if report["raw_count"] != 362: errors.append(f"raw_count expected 362, got {report['raw_count']}")
    if report["clean_count"] != 362: errors.append(f"clean_count expected 362, got {report['clean_count']}")
    if report["raw_duplicate_business_keys"] != 0: errors.append("raw duplicate business keys != 0")
    if report["clean_duplicate_business_keys"] != 0: errors.append("clean duplicate business keys != 0")
    if len(report["departments"]) != 2: errors.append("expected 2 departments")
    if len(report["balance_check_rows"]) != 2: errors.append("expected exactly 2 patient-balance CHECK rows")
    if report["latest_run"]["quality_error_count"] != 0: errors.append("latest run has DQ ERROR")
    if errors:
        print("\nV2-11 VERIFY: FAIL")
        for e in errors: print(" -", e)
        raise SystemExit(1)
    print("\nV2-11 VERIFY: PASS")


if __name__ == "__main__":
    main()
