# V2-11 Windows Quickstart

> Tài liệu lịch sử của giai đoạn này, không phải hướng dẫn vận hành hiện hành. Mốc ngày, số dòng và giới hạn bên dưới có thể đã thay đổi. Để sử dụng phiên bản hiện tại, xem [hướng dẫn Windows](WINDOWS_QUICKSTART.md) và [quy trình vận hành](OPERATIONS.md).

Verified local infrastructure for this project:
- Windows host
- Docker container: `sql2022-v2`
- SQL Server 2022 Developer Edition
- Host endpoint: `localhost:1434`
- Persistent Docker volume: `hospital_bed_v2_sql_data` -> `/var/opt/mssql`

## 1. Check Python
Run in PowerShell from any directory:

```powershell
python --version
py --version
```

Use Python 3.10-3.13 for the supplied pinned dependencies. If `python` is not found but `py` works, replace `python` with `py` in the commands below.

## 2. Extract project and enter it

```powershell
cd <folder-containing-hospital-bed-forecast-v2-clean>
cd hospital-bed-forecast-v2-clean
```

## 3. Create virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, run this only for the current PowerShell process and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 4. Create local `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Keep these values:

```text
V2_DB_HOST=localhost
V2_DB_PORT=1434
V2_DB_NAME=HospitalBedForecastV2
V2_DB_SCHEMA=dbo
V2_DB_USER=sa
V2_DB_DRIVER=pymssql
```

Replace only `V2_DB_PASSWORD=CHANGE_ME_LOCALLY` with your V2 container SA password. Do not send the password to ChatGPT and do not commit `.env`.

## 5. Run code-level tests

```powershell
python -m pytest -q
```

Expected: `4 passed`.

## 6. Create database and apply migration

```powershell
python scripts/setup_db.py
```

Expected on first run:
- `Created database: HospitalBedForecastV2`
- `Applied: 001_core_schema.sql`
- `V2-11 SQL Foundation migration complete.`

A second run must be safe and should report the database already exists and the migration is skipped.

## 7. Bootstrap the two verified Excel files

Put `HSNoi.xlsx` and `hsNgoai.xlsx` somewhere on your local machine and use their actual paths:

```powershell
python scripts/bootstrap_excel.py --noi "C:\path\to\HSNoi.xlsx" --ngoai "C:\path\to\hsNgoai.xlsx"
```

Expected first run:
- status `BOOTSTRAP_COMPLETED`
- rows `362`
- raw inserted `362`
- quality ERROR `0`
- quality WARNING `0`
- quality CHECK `2`

## 8. Verify V2-11

```powershell
python scripts/verify_v2_11.py
```

Expected final line: `V2-11 VERIFY: PASS`.

## 9. Idempotency rerun
Run the same bootstrap command a second time, then verify again.

Expected second bootstrap:
- RAW/CLEAN still `362`
- raw `unchanged=362`
- raw `updated=0`
- `raw_revision_gt1=0`
- `V2-11 VERIFY: PASS`

Copy the terminal output of steps 1, 5, 6, 7, 8 and the second bootstrap+verify back to ChatGPT. Do not include the `.env` file or password.
