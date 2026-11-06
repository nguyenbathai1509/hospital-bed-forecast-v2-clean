from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_pipeline_runner, get_read_repository


class FakePipelineDataRepository:
    def latest_pipeline_run_id(self):
        return "DAY_LATEST"

    def pipeline_run_exists(self, run_id: str):
        return run_id in {"DAY_LATEST", "DAY_OLD"}

    def pipeline_runs(self, *, status, limit, offset):
        rows = [
            {
                "run_id": "DAY_LATEST",
                "business_date": date(2026, 6, 30),
                "source_mode": "EXCEL_BOOTSTRAP",
                "data_version": "excel-sha256:test",
                "status": "DATA_READY",
                "started_at": datetime(2026, 9, 7, 17, 8, 49),
                "completed_at": datetime(2026, 9, 7, 17, 9, 9),
                "rows_extracted": 362,
                "quality_error_count": 0,
                "quality_warning_count": 0,
                "quality_check_count": 2,
                "error_message": None,
            }
        ]

        if status is not None:
            rows = [row for row in rows if row["status"] == status]

        return rows[offset : offset + limit]

    def data_quality_issues(
        self,
        *,
        pipeline_run_id,
        business_date,
        department_id,
        severity,
        limit,
        offset,
    ):
        rows = [
            {
                "issue_id": 1,
                "pipeline_run_id": pipeline_run_id,
                "business_date": date(2026, 3, 20),
                "department_id": 343,
                "rule_id": "DQ08",
                "severity": "CHECK",
                "field_name": "occupied_end",
                "expected_value": "54",
                "actual_value": "53",
                "difference_value": -1.0,
                "message": "Patient balance requires manual review.",
                "detected_at": datetime(2026, 9, 7, 17, 8, 55),
                "is_resolved": False,
            }
        ]

        if business_date is not None:
            rows = [row for row in rows if row["business_date"] == business_date]
        if department_id is not None:
            rows = [row for row in rows if row["department_id"] == department_id]
        if severity is not None:
            rows = [row for row in rows if row["severity"] == severity]

        return rows[offset : offset + limit]

    def department_exists(self, department_id: int):
        return department_id in {343, 344}

    def history_rows(
        self,
        *,
        department_id,
        start_date,
        end_date,
        limit,
        offset,
    ):
        rows = [
            {
                "business_date": date(2026, 6, 30),
                "department_id": department_id,
                "department_code": "K481" if department_id == 343 else "K482",
                "department_name": (
                    "Khoa Hồi Sức Tích Cực"
                    if department_id == 343
                    else "Khoa Hồi Sức Tích Cực - Ngoại Khoa"
                ),
                "planned_beds": 55 if department_id == 343 else 45,
                "occupied_start": 48,
                "admissions": 8,
                "transfer_in": 2,
                "discharges": 7,
                "transfer_out": 3,
                "occupied_end": 48,
                "occupied_beds": 48,
                "net_flow": 0,
                "occupancy_rate_pct": 87.2727272727,
                "quality_flag": "PASS",
                "source_revision_no": 1,
            }
        ]

        return rows[offset : offset + limit]


def _client(
    *,
    repo: FakePipelineDataRepository | None = None,
    runner=None,
) -> TestClient:
    app = create_app()

    if repo is not None:
        app.dependency_overrides[get_read_repository] = lambda: repo

    if runner is not None:
        app.dependency_overrides[get_pipeline_runner] = lambda: runner

    return TestClient(app)


def test_openapi_contains_master_v2_pipeline_data_routes():
    client = TestClient(create_app())

    paths = client.get("/openapi.json").json()["paths"]

    assert "/pipeline/runs" in paths
    assert "/pipeline/run" in paths
    assert "/data-quality" in paths
    assert "/history" in paths


def test_pipeline_runs_returns_quality_and_history_contract():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get("/pipeline/runs?status=DATA_READY")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["rows"][0]["run_id"] == "DAY_LATEST"
    assert body["rows"][0]["quality"] == {
        "ERROR": 0,
        "WARNING": 0,
        "CHECK": 2,
    }


def test_pipeline_runs_rejects_invalid_status_with_422_contract():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get("/pipeline/runs?status=NOT_A_STATUS")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_data_quality_defaults_to_latest_pipeline_run_and_filters():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get(
        "/data-quality?department_id=343&severity=CHECK"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_run_id"] == "DAY_LATEST"
    assert body["count"] == 1
    assert body["rows"][0]["rule_id"] == "DQ08"
    assert body["rows"][0]["severity"] == "CHECK"


def test_data_quality_unknown_explicit_pipeline_run_returns_404():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get(
        "/data-quality?pipeline_run_id=DAY_MISSING"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PIPELINE_RUN_NOT_FOUND"


def test_history_returns_clean_occupancy_and_flow_contract():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get(
        "/history?department_id=343&start_date=2026-06-01&end_date=2026-06-30"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["department_id"] == 343
    assert body["count"] == 1
    assert body["rows"][0]["occupied_beds"] == 48
    assert body["rows"][0]["net_flow"] == 0
    assert body["rows"][0]["quality_flag"] == "PASS"


def test_history_rejects_reverse_date_range_with_400():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get(
        "/history?department_id=343&start_date=2026-07-01&end_date=2026-06-30"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_history_unknown_department_returns_404():
    client = _client(repo=FakePipelineDataRepository())

    response = client.get("/history?department_id=999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DEPARTMENT_NOT_FOUND"


def test_pipeline_run_delegates_to_existing_daily_pipeline_service_contract():
    calls = {"count": 0}

    def runner():
        calls["count"] += 1
        return {
            "run_id": "DAY_TRIGGERED",
            "status": "DATA_READY",
            "business_date": "2026-06-30",
            "data_version": "excel-sha256:test",
            "feature_version": "v2.0",
            "rows": 362,
            "quality": {
                "ERROR": 0,
                "WARNING": 0,
                "CHECK": 2,
            },
            "stages": {
                "SOURCE_READINESS": "PASS",
                "ACTUAL_MATCHING": {
                    "status": "WAITING_FOR_ACTUAL",
                },
                "MONITORING": {
                    "status": "WAITING_FOR_ACTUAL",
                },
            },
        }

    client = _client(runner=runner)

    response = client.post("/pipeline/run")

    assert response.status_code == 200
    assert calls["count"] == 1
    body = response.json()
    assert body["run_id"] == "DAY_TRIGGERED"
    assert body["status"] == "DATA_READY"
    assert body["rows"] == 362
    assert body["quality"]["CHECK"] == 2


def test_pipeline_run_preserves_waiting_as_business_state_not_fake_success():
    def runner():
        return {
            "run_id": "DAY_WAITING",
            "status": "WAITING",
            "business_date": None,
            "readiness": {
                "ready": False,
                "reason": "SOURCE_FILES_MISSING",
                "details": {
                    "missing": ["data/HSNoi.xlsx"],
                },
            },
            "stages": {
                "SOURCE_READINESS": "WAITING",
            },
        }

    client = _client(runner=runner)

    response = client.post(
        "/pipeline/run",
        json={"source_mode": "EXCEL_BOOTSTRAP"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "WAITING"
    assert body["readiness"]["reason"] == "SOURCE_FILES_MISSING"


def test_pipeline_run_rejects_unknown_source_mode_before_runner():
    client = _client(runner=lambda: (_ for _ in ()).throw(AssertionError()))

    response = client.post(
        "/pipeline/run",
        json={"source_mode": "LIVE_SQL_NOT_CONFIGURED"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"