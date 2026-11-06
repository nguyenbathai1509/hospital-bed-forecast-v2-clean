"""Opt-in real-backend acceptance in a newly created, isolated SQL database.

Never drops/resets an existing database. Retains evidence and test artifacts.
Usage: python -m scripts.run_e2e_acceptance prepare
       python -m scripts.run_e2e_acceptance run --manifest <printed manifest>
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

import httpx
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "reports" / "e2e_acceptance"
TEST_DATABASE = "HospitalBedForecastV2_E2E"
FILES = ("HSNoi.xlsx", "hsNgoai.xlsx")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def assert_isolated_name(protected, target):
    require(target == TEST_DATABASE, "Only the explicitly approved E2E database is allowed")
    require(protected.casefold() != target.casefold(), "Refusing to use the configured database as a test target")


def sandbox_path(path):
    resolved = Path(path).resolve()
    require(resolved.is_relative_to(EVIDENCE_ROOT.resolve()) and resolved != EVIDENCE_ROOT.resolve(),
            "Test files must stay inside reports/e2e_acceptance/<run>")
    require(not resolved.is_relative_to(ROOT / "data"), "Refusing to edit source data")
    return resolved


def save(path, value):
    sandbox_path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def digest_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def protected_snapshot():
    from src.config import settings
    from src.db.engine import create_sql_engine
    assert_isolated_name(settings.db_name, TEST_DATABASE)
    engine = create_sql_engine()
    tables = {}
    with engine.connect() as conn:
        require(conn.execute(text("SELECT DB_NAME()")).scalar() == settings.db_name, "Unexpected protected database")
        names = conn.execute(text("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo') ORDER BY name")).scalars().all()
        for name in names:
            # Only hashes/counts leave this read-only snapshot; no row contents are saved.
            rows = conn.exec_driver_sql(f"SELECT * FROM [dbo].[{name.replace(']', ']]')}]").mappings()
            hashes = sorted(hashlib.sha256(json.dumps(dict(row), sort_keys=True, default=str).encode()).hexdigest() for row in rows)
            tables[name] = {"count": len(hashes), "sha256": hashlib.sha256("".join(hashes).encode()).hexdigest()}
    engine.dispose()
    paths = [ROOT / "data" / name for name in FILES] + [ROOT / ".env"]
    paths += sorted((ROOT / "models" / "registry").rglob("*"))
    return {"database": settings.db_name, "tables": tables,
            "files": {p.relative_to(ROOT).as_posix(): digest_file(p) for p in paths if p.is_file()}}


def child_environment(project):
    from src.config import settings
    assert_isolated_name(settings.db_name, TEST_DATABASE)
    env = os.environ.copy()
    env.update(V2_DB_NAME=TEST_DATABASE, V2_DEMO_RESET_ENABLED="false",
               PYTHONPATH=str(sandbox_path(project)), PYTHONIOENCODING="utf-8")
    return env


def run_child(project, args):
    subprocess.run([sys.executable, *args], cwd=sandbox_path(project), env=child_environment(project), check=True)


def test_engine(manifest):
    from src.config import settings
    from src.db.engine import create_sql_engine
    assert_isolated_name(settings.db_name, manifest["database"])
    engine = create_sql_engine(cfg=replace(settings, db_name=manifest["database"]))
    with engine.connect() as conn:
        require(conn.execute(text("SELECT DB_NAME()")).scalar() == TEST_DATABASE, "Database target mismatch")
        marker = conn.execute(text("SELECT token FROM dbo.e2e_environment")).scalar_one()
        require(marker == manifest["token"], "Test database is not owned by this run")
    return engine


def prepare():
    from src.config import settings
    from src.db.engine import create_sql_engine
    assert_isolated_name(settings.db_name, TEST_DATABASE)
    master = create_sql_engine(database="master")
    with master.connect() as conn:
        require(conn.execute(text("SELECT DB_ID(:name)"), {"name": TEST_DATABASE}).scalar() is None,
                "E2E database already exists; it will NOT be reused, overwritten or dropped")
    token = uuid.uuid4().hex
    folder = sandbox_path(EVIDENCE_ROOT / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{token[:8]}")
    folder.mkdir(parents=True, exist_ok=False)
    project = folder / "project"
    project.mkdir()
    manifest = {"database": TEST_DATABASE, "protected_database": settings.db_name, "token": token,
                "project": str(project), "state": "PREPARING", "events": []}
    path = folder / "manifest.json"
    save(path, manifest)
    save(folder / "protected_before.json", protected_snapshot())
    for name in ("src", "app", "scripts", "migrations", ".streamlit"):
        shutil.copytree(ROOT / name, project / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (project / "data").mkdir()
    for name in FILES:
        shutil.copy2(ROOT / "data" / name, project / "data" / name)
    with master.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # Check again immediately before creation; CREATE itself also fails if a peer won.
        require(conn.execute(text("SELECT DB_ID(:name)"), {"name": TEST_DATABASE}).scalar() is None, "Target appeared during setup")
        conn.exec_driver_sql(f"CREATE DATABASE [{TEST_DATABASE}]")
    master.dispose()
    run_child(project, ["-m", "scripts.setup_db"])
    engine = create_sql_engine(cfg=replace(settings, db_name=TEST_DATABASE))
    with engine.begin() as conn:
        require(conn.execute(text("SELECT DB_NAME()")).scalar() == TEST_DATABASE, "Database target mismatch")
        conn.exec_driver_sql("CREATE TABLE dbo.e2e_environment (token VARCHAR(32) NOT NULL PRIMARY KEY)")
        conn.execute(text("INSERT INTO dbo.e2e_environment(token) VALUES (:token)"), {"token": token})
    engine.dispose()
    # Verify actual Python module resolution and database inside the copied worker environment.
    run_child(project, ["-c", "from pathlib import Path; from sqlalchemy import text; import src.config as c; from src.db.engine import create_sql_engine; "
               "assert Path(c.__file__).resolve().is_relative_to(Path.cwd()); assert c.settings.db_name=='HospitalBedForecastV2_E2E'; "
               "e=create_sql_engine(); conn=e.connect(); assert conn.execute(text('SELECT DB_NAME()')).scalar()=='HospitalBedForecastV2_E2E'; conn.close(); e.dispose(); print('ISOLATION VERIFIED')"])
    manifest["state"] = "PREPARED"
    save(path, manifest)
    print(f"MANIFEST={path}", flush=True)


def append_days(project, days):
    from openpyxl import load_workbook
    final_date = None
    for name in FILES:
        path = sandbox_path(Path(project) / "data" / name)
        # Freeze Excel's cached values before appending: openpyxl does not
        # calculate formulas and otherwise drops the cached occupancy rates.
        wb = load_workbook(path, data_only=True)
        ws = wb["Export Worksheet"]
        last = [cell.value for cell in ws[ws.max_row]]
        for _ in range(days):
            day = last[0] + timedelta(days=1)
            occupied = int(last[12])
            # Synthetic, balanced stationary day; no claim these are real future observations.
            row = [day, ("T1", "T2", "T3", "T4", "T5", "T6", "CN")[day.weekday()], day.month,
                   *last[3:7], occupied, 0, 0, 0, 0, occupied, occupied, "OK", occupied / int(last[6]) * 100]
            ws.append(row)
            last = row
        current_date = last[0].date().isoformat()
        require(final_date in (None, current_date), "Source dates are not aligned")
        final_date = current_date
        wb.save(path)
        wb.close()
    return final_date


def run(manifest_path, port):
    path = sandbox_path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(manifest["state"] == "PREPARED", "Run is not newly prepared; refusing to replay mutations")
    project = sandbox_path(manifest["project"])
    require(project.parent == path.parent, "Manifest/project mismatch")
    engine = test_engine(manifest)
    # Never attach to an existing server on the selected port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    manifest["state"] = "RUNNING"
    save(path, manifest)

    def event(step, **details):
        row = {"step": step, "time": datetime.now(timezone.utc).isoformat(), **details}
        manifest["events"].append(row)
        save(path, manifest)
        print(json.dumps(row, ensure_ascii=True, default=str), flush=True)

    def counts():
        with engine.connect() as conn:
            return {name: conn.exec_driver_sql(f"SELECT COUNT_BIG(*) FROM dbo.[{name}]").scalar_one()
                    for name in ("raw_bed_daily", "clean_bed_daily", "model_candidates", "forecast_drafts", "official_forecasts", "official_actual_matches")}

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with (path.parent / "api.log").open("ab") as log:
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", str(port)],
                                  cwd=project, env=child_environment(project), stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags)
    manifest["api_pid"] = server.pid
    save(path, manifest)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            for _ in range(60):
                require(server.poll() is None, "Test API failed to start; inspect api.log")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("Test API startup timeout")

            def api(method, route, **kwargs):
                response = client.request(method, route, **kwargs)
                require(response.is_success, f"{method} {route}: HTTP {response.status_code}: {response.text[:1500]}")
                return response.json()

            require(api("GET", "/data/status")["status"] == "NO_DATA_READY", "Test database was not empty")
            baseline = api("POST", "/pipeline/run", json={"source_mode": "EXCEL_BOOTSTRAP"})
            require(baseline["status"] == "DATA_READY", "Initial pipeline did not become ready")
            event("baseline_pipeline", business_date=baseline["business_date"], counts=counts())
            new_date = append_days(project, 1)
            updated = api("POST", "/pipeline/run", json={"source_mode": "EXCEL_BOOTSTRAP"})
            require(updated["status"] == "DATA_READY" and updated["business_date"] == new_date, "New data was not adopted")
            event("new_day_pipeline", business_date=new_date, quality=updated["quality"], counts=counts())
            job = api("POST", "/training/start", json={"requested_by": "isolated-e2e", "random_seed": 42})
            manifest["job_id"] = job["job_id"]
            event("training_started", job_id=job["job_id"], status=job["status"])
            deadline = time.monotonic() + 7200
            last_progress = None
            while time.monotonic() < deadline:
                job = api("GET", f"/training/status/{manifest['job_id']}")
                progress = (job["status"], counts()["model_candidates"])
                if progress != last_progress:
                    event("training_progress", status=progress[0], candidates=progress[1])
                    last_progress = progress
                if job["status"] in {"COMPLETED", "FAILED"}:
                    break
                time.sleep(10)
            require(job["status"] == "COMPLETED", f"Training did not complete: {job}")
            result = api("GET", f"/training/results/{job['training_run_id']}")
            candidates = result["candidates"]
            require(len(candidates) == 8, "Expected all 4 model families for 2 horizons")
            evaluations = []
            for candidate in candidates:
                evaluation = api("GET", f"/training/evaluation/{job['training_run_id']}", params={
                    "horizon": candidate["horizon"], "model_family": candidate["model_family"]})
                require(evaluation["count"] > 0 and evaluation["split"]["test_end"] == new_date,
                        "Missing evaluation or split did not advance with new data")
                evaluations.append({"family": candidate["model_family"], "horizon": candidate["horizon"], "rows": evaluation["count"]})
            event("training_and_evaluation_completed", run_id=job["training_run_id"], evaluations=evaluations)
            promotion_body = {"horizons": [1, 3], "requested_by": "isolated-e2e", "reason": "Isolated full-backend acceptance"}
            plan = api("POST", "/models/promote", json=promotion_body)
            require(plan["status"] == "CONFIRMATION_REQUIRED", "Promotion plan missing")
            promoted = api("POST", "/models/promote", json={**promotion_body, "confirmation": "I_CONFIRM_PROMOTION"})
            require(promoted["status"] == "COMPLETED", "Promotion failed")
            event("models_promoted", horizons=[1, 3])
            dept_ids = [row["department_id"] for row in api("GET", "/departments")]
            request = {"origin_date": new_date, "department_ids": dept_ids, "horizons": [1, 3]}
            before_preview = counts()
            preview = api("POST", "/forecasts/preview", json={**request, "mode": "PRODUCTION"})
            require(not preview["persisted"] and counts() == before_preview, "Preview persisted lifecycle records")
            drafts = api("POST", "/forecasts/production", json={**request, "created_by": "isolated-e2e"})
            require(drafts["created_count"] == len(dept_ids) * 2, "Drafts missing")
            reused = api("POST", "/forecasts/production", json={**request, "created_by": "isolated-e2e"})
            require(reused["created_count"] == 0 and reused["reused_count"] == len(dept_ids) * 2, "Duplicate draft creation")
            official_body = {"origin_date": new_date, "confirmed_by": "isolated-e2e"}
            official_plan = api("POST", "/forecasts/official/confirm", json=official_body)
            require(official_plan["draft_count"] == len(dept_ids) * 2, "Official plan scope mismatch")
            confirmed = api("POST", "/forecasts/official/confirm", json={**official_body, "confirmation": "I_CONFIRM_OFFICIAL"})
            require(confirmed["status"] == "COMPLETED", "Official confirmation failed")
            officials = api("GET", "/forecasts/official", params={"origin_date": new_date})["rows"]
            require(len(officials) == len(dept_ids) * 2, "Official records missing")
            event("forecast_lifecycle_completed", official_count=len(officials), preview_persisted=False, duplicate_drafts=False)
            # Explicit monitoring verifies the waiting state after new officials exist.
            waiting = api("POST", "/monitoring/run", json={})
            require(waiting["waiting_for_actual_count"] == len(officials), "Future actuals should still be pending")
            event("monitoring_waiting", waiting_for_actual_count=waiting["waiting_for_actual_count"])
            actual_date = append_days(project, 3)
            matured = api("POST", "/pipeline/run", json={"source_mode": "EXCEL_BOOTSTRAP"})
            require(matured["status"] == "DATA_READY", "Pipeline with new actuals failed")
            monitoring = api("GET", "/monitoring")
            require(monitoring["run"]["matched_total_count"] == len(officials), "Not all officials matched new actuals")
            require(api("GET", "/forecasts/official", params={"origin_date": new_date})["rows"] == officials,
                    "Official forecasts changed after new data")
            stable = counts()
            repeat = api("POST", "/pipeline/run", json={"source_mode": "EXCEL_BOOTSTRAP"})
            require(repeat["status"] == "DATA_READY" and counts() == stable, "Identical source replay duplicated data")
            event("new_actuals_and_idempotency_verified", business_date=actual_date,
                  matched_total_count=monitoring["run"]["matched_total_count"], counts=stable)
            manifest["state"] = "PASSED"
    except BaseException as exc:
        manifest["state"] = "FAILED"
        event("failure", exception_type=type(exc).__name__, message=str(exc)[:3000])
        raise
    finally:
        if sys.platform == "win32" and server.poll() is None:
            # The Windows venv launcher may own a second Python process. Stop
            # only the still-running process tree created by this exact Popen.
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        elif server.poll() is None:
            server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        engine.dispose()
        after = protected_snapshot()
        save(path.parent / "protected_after.json", after)
        before = json.loads((path.parent / "protected_before.json").read_text(encoding="utf-8"))
        manifest["protected_unchanged"] = before == after
        if before != after:
            manifest["state"] = "FAILED"
        save(path, manifest)
        print(f"FINAL_STATE={manifest['state']} PROTECTED_UNCHANGED={before == after}", flush=True)


def verify_fixture(manifest_path):
    """Revalidate the first run's Excel-cache repair without touching ML artifacts.

    Retain the original test inputs and prior evidence. Check that the repaired
    workbook changes no numerical features/targets and no official predictions.
    """
    path = sandbox_path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(manifest["state"] == "PASSED" and "fixture_revalidation" not in manifest,
            "Fixture revalidation requires a completed, not-yet-revalidated run")
    project = sandbox_path(manifest["project"])
    require(project.parent == path.parent, "Manifest/project mismatch")
    engine = test_engine(manifest)

    def value_hashes():
        hashes = {}
        with engine.connect() as conn:
            for table, excluded in (
                ("bed_features_daily", {"feature_id", "built_at", "source_revision_no"}),
                ("ml_samples", {"sample_id", "data_version", "matured_at"}),
                ("official_forecasts", set()),
            ):
                values = [json.dumps({k: v for k, v in row.items() if k not in excluded}, sort_keys=True, default=str)
                          for row in conn.exec_driver_sql(f"SELECT * FROM dbo.[{table}]").mappings()]
                hashes[table] = hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()
        return hashes

    before_values = value_hashes()
    with engine.connect() as conn:
        latest = conn.exec_driver_sql("SELECT MAX(business_date) FROM dbo.clean_bed_daily").scalar_one()
    from openpyxl import load_workbook
    backup = sandbox_path(path.parent / "fixture_before_repair")
    backup.mkdir(exist_ok=False)
    for name in FILES:
        shutil.copy2(project / "data" / name, backup / name)
        shutil.copy2(ROOT / "data" / name, project / "data" / name)
    workbook = load_workbook(project / "data" / FILES[0], read_only=True, data_only=True)
    source_end = list(workbook["Export Worksheet"].values)[-1][0].date()
    workbook.close()
    require(latest > source_end, "Test data must contain appended synthetic days")
    require(append_days(project, (latest - source_end).days) == latest.isoformat(), "Rebuilt source date mismatch")
    run_child(project, ["-c", "import json; from pathlib import Path; from src.services.daily_pipeline_service import run_daily_excel_pipeline; "
               "r=run_daily_excel_pipeline('data/HSNoi.xlsx','data/hsNgoai.xlsx'); "
               "Path('reports/fixture_revalidation.json').write_text(json.dumps(r,default=str),encoding='utf-8'); "
               "print(json.dumps({'status':r['status'],'quality':r.get('quality')})); "
               "assert r['status']=='DATA_READY' and r['quality']['ERROR']==0 and r['quality']['WARNING']==0"])
    require(value_hashes() == before_values, "Numerical features, targets or official forecasts changed during fixture repair")
    evidence = json.loads((project / "reports/fixture_revalidation.json").read_text(encoding="utf-8"))
    manifest["fixture_revalidation"] = {"quality": evidence["quality"], "business_date": evidence["business_date"],
                                        "feature_target_official_hashes_unchanged": True,
                                        "note": "Initial fixture save cleared Excel formula caches; cached source values are now preserved."}
    engine.dispose()
    after = protected_snapshot()
    before = json.loads((path.parent / "protected_before.json").read_text(encoding="utf-8"))
    require(after == before, "Protected environment changed")
    save(path.parent / "protected_after.json", after)
    save(path, manifest)
    print("FIXTURE_REVALIDATION=PASSED PROTECTED_UNCHANGED=True", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "verify-fixture"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        require(args.manifest is not None, "--manifest is required")
        if args.action == "verify-fixture":
            verify_fixture(args.manifest)
        else:
            run(args.manifest, args.port)


if __name__ == "__main__":
    main()
