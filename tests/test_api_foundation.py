from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_read_repository


class FakeReadRepository:
    def __init__(self, *, has_data_ready: bool = True):
        self.has_data_ready = has_data_ready

    def latest_data_status(self):
        if not self.has_data_ready:
            return None

        return {
            "run_id": "DAY_TEST",
            "business_date": date(2026, 6, 30),
            "source_mode": "EXCEL_BOOTSTRAP",
            "data_version": "excel-sha256:test",
            "rows_extracted": 362,
            "quality_error_count": 0,
            "quality_warning_count": 0,
            "quality_check_count": 2,
            "completed_at": datetime(2026, 9, 7, 17, 9, 9),
        }

    def latest_actual_date(self):
        return date(2026, 6, 30)

    def active_department_count(self):
        return 2

    def departments(self):
        return [
            {
                "department_id": 343,
                "department_code": "K481",
                "department_name": "Khoa Hồi Sức Tích Cực",
                "planned_beds": 55,
                "is_active": True,
            },
            {
                "department_id": 344,
                "department_code": "K482",
                "department_name": "Khoa Hồi Sức Tích Cực - Ngoại Khoa",
                "planned_beds": 45,
                "is_active": True,
            },
        ]


def _client(repo: FakeReadRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_read_repository] = lambda: repo
    return TestClient(app)


def test_health_is_db_independent_and_returns_api_identity():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "service": "hospital-bed-forecast-v2",
        "api_version": "v2",
    }


def test_openapi_contains_v2_foundation_routes():
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/data/status" in paths
    assert "/departments" in paths


def test_data_status_maps_latest_data_ready_contract():
    client = _client(FakeReadRepository())

    response = client.get("/data/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DATA_READY"
    assert body["pipeline_run_id"] == "DAY_TEST"
    assert body["business_date"] == "2026-06-30"
    assert body["latest_actual_date"] == "2026-06-30"
    assert body["rows_extracted"] == 362
    assert body["quality"] == {
        "ERROR": 0,
        "WARNING": 0,
        "CHECK": 2,
    }
    assert body["active_department_count"] == 2


def test_data_status_handles_no_data_ready_without_fabricating_state():
    client = _client(FakeReadRepository(has_data_ready=False))

    response = client.get("/data/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NO_DATA_READY"
    assert body["pipeline_run_id"] is None
    assert body["business_date"] is None
    assert body["latest_actual_date"] == "2026-06-30"
    assert body["quality"] == {
        "ERROR": 0,
        "WARNING": 0,
        "CHECK": 0,
    }


def test_departments_returns_active_department_read_model():
    client = _client(FakeReadRepository())

    response = client.get("/departments")

    assert response.status_code == 200
    body = response.json()
    assert [row["department_id"] for row in body] == [343, 344]
    assert [row["planned_beds"] for row in body] == [55, 45]
    assert all(row["is_active"] is True for row in body)


def test_api_contract_rejects_unknown_path_with_404():
    client = TestClient(create_app())

    response = client.get("/does-not-exist")

    assert response.status_code == 404