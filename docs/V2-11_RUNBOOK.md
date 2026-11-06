# V2-11 Runbook - SQL Foundation (local SQL Server on Docker)

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](WINDOWS_QUICKSTART.md) và [quy trình vận hành](OPERATIONS.md).

## Why Excel bootstrap exists
The hospital has only provided `HSNoi.xlsx` and `hsNgoai.xlsx`; there is no read-only hospital database connection yet. V2 therefore uses a **one-time/local bootstrap source adapter** for these two exports. After import, the product reads operational data from the local SQL Server. When hospital SQL access becomes available, add `HospitalSqlSourceAdapter`; do not rewrite RAW/CLEAN/FEATURE contracts.

This is an implementation extension compatible with V2 MASTER, not a change to D04. Never pretend the Excel bootstrap is a live HIS/SQL connection.

## Default local database
- Database: `HospitalBedForecastV2`
- Schema: `dbo`
- Host/port for the verified V2 Docker container: `localhost:1434` (configurable via `.env`)
- Credentials: local only; password must not be sent to ChatGPT or committed.

## Phase-1 tables
`departments`, `pipeline_runs`, `raw_bed_daily`, `data_quality_issues`, `clean_bed_daily`, `bed_features_daily`, `ml_samples`.

Feature and ML tables are created now as contracts, but **V2-11 does not populate them**. Feature construction and target maturation belong to V2-12 Daily Pipeline and are not marked complete until SQL execution is verified.

## Run sequence
1. Copy `.env.example` to `.env`; keep `localhost:1434`, fill your local SA password only on your machine.
2. Install dependencies in a virtual environment.
3. `python scripts/setup_db.py`
4. `python scripts/bootstrap_excel.py --noi <path>/HSNoi.xlsx --ngoai <path>/hsNgoai.xlsx`
5. `python scripts/verify_v2_11.py`
6. Run the same bootstrap command again, then run verify again. Expected: RAW/CLEAN remain 362 rows and no duplicate business key. `raw_revision_gt1` must remain 0 when the files are unchanged.

## Expected evidence from the supplied workbooks
- RAW = 362 rows
- CLEAN = 362 rows
- 2 departments: 343/K481/55 beds and 344/K482/45 beds
- 181 days/department, 2026-01-01 through 2026-06-30
- 0 DQ ERROR
- exactly two DQ07 CHECK rows, department 343 on 2026-03-20 and 2026-03-21, with balance error -1 and +1
- no duplicate `(business_date, department_id)`

## Do not continue to V2-12 if
- migration fails;
- counts differ;
- any DQ ERROR appears;
- rerun increments revision numbers even though the input files are unchanged;
- there is a duplicate business key.
