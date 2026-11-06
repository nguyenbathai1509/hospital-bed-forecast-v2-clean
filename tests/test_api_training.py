from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import (
    get_read_repository,
    get_training_job_launcher,
    get_training_job_service,
)
from src.api.training_jobs import NoDataReadyError


RUN_ID = "TRN_TEST"
JOB_ID = "TJOB_TEST"


class FakeTrainingJobService:
    def __init__(self, *, reused: bool = False, no_data: bool = False):
        self.reused = reused
        self.no_data = no_data
        self.start_calls = []
        self.launch_failures = []

    def start_job(self, *, requested_by: str, random_seed: int):
        self.start_calls.append((requested_by, random_seed))
        if self.no_data:
            raise NoDataReadyError("No DATA_READY Daily Pipeline run exists")
        return {
            "job_id": JOB_ID,
            "business_date": date(2026, 6, 30),
            "source_pipeline_run_id": "DAY_TEST",
            "status": "COMPLETED" if self.reused else "PENDING",
            "requested_by": requested_by,
            "random_seed": random_seed,
            "training_run_id": RUN_ID if self.reused else None,
            "reused": self.reused,
            "should_schedule": not self.reused,
        }

    def mark_launch_failed(self, job_id: str, exc: Exception):
        self.launch_failures.append((job_id, type(exc).__name__))


class FakeTrainingJobLauncher:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.launched = []

    def launch(self, job_id: str):
        if self.fail:
            raise OSError("worker unavailable")
        self.launched.append(job_id)


class FakeTrainingReadRepository:
    def training_job(self, job_id: str):
        if job_id != JOB_ID:
            return None
        return {
            "job_id": JOB_ID,
            "business_date": date(2026, 6, 30),
            "source_pipeline_run_id": "DAY_TEST",
            "status": "COMPLETED",
            "requested_by": "api",
            "random_seed": 42,
            "training_run_id": RUN_ID,
            "created_at": datetime(2026, 9, 8, 1, 0, 0),
            "started_at": datetime(2026, 9, 8, 1, 0, 1),
            "completed_at": datetime(2026, 9, 8, 1, 0, 2),
            "error_message": None,
        }

    def training_runs(self, *, status, limit, offset):
        rows = [self.training_run(RUN_ID)]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows[offset : offset + limit]

    def training_run(self, run_id: str):
        if run_id != RUN_ID:
            return None
        return {
            "run_id": RUN_ID,
            "business_date": date(2026, 6, 30),
            "status": "COMPLETED",
            "triggered_by": "manual",
            "scope": "GLOBAL",
            "data_start": date(2026, 1, 4),
            "data_end": date(2026, 6, 30),
            "data_version": "excel-sha256:test",
            "feature_version": "v2.0",
            "row_count": 704,
            "department_count": 2,
            "random_seed": 42,
            "training_contract_version": "v2.0",
            "completed_candidate_count": 8,
            "started_at": datetime(2026, 9, 7, 10, 59, 13),
            "completed_at": datetime(2026, 9, 7, 11, 2, 0),
            "error_message": None,
        }

    def candidates_for_training_run(self, run_id: str):
        if run_id != RUN_ID:
            return []
        return [
            {
                "candidate_id": f"{RUN_ID}_H1_RF",
                "run_id": RUN_ID,
                "horizon": 1,
                "model_family": "RF",
                "registry_status": "PRODUCTION",
                "is_recommended": True,
                "artifact_type": "SKLEARN_JOBLIB",
                "inference_type": "TABULAR_28",
                "feature_version": "v2.0",
                "data_version": "excel-sha256:test",
                "mae": 2.2548,
                "rmse": 3.0,
                "wape": 4.5,
                "r2": 0.2,
                "bias": -0.1,
                "p90_abs_error": 5.0,
                "max_abs_error": 8.0,
                "within_2_rate": 0.59,
                "underprediction_rate": 0.4,
                "underprediction_mae": 2.1,
                "created_at": datetime(2026, 9, 7, 11, 0, 0),
            }
        ]

    def department_metrics_for_training_run(self, run_id: str):
        return [
            {
                "candidate_id": f"{RUN_ID}_H1_RF",
                "department_id": 343,
                "sample_count": 37,
                "mae": 2.1,
                "rmse": 2.8,
                "wape": 4.2,
                "r2": 0.3,
                "bias": -0.2,
                "p90_abs_error": 4.8,
                "max_abs_error": 7.0,
                "within_2_rate": 0.6,
                "underprediction_rate": 0.4,
                "underprediction_mae": 2.0,
            }
        ]

    def recommendations_for_training_run(self, run_id: str):
        return [
            {
                "recommendation_id": f"REC_{RUN_ID}_H1",
                "run_id": RUN_ID,
                "horizon": 1,
                "best_candidate_id": f"{RUN_ID}_H1_SVR",
                "champion_candidate_id": f"{RUN_ID}_H1_RF",
                "recommended_candidate_id": f"{RUN_ID}_H1_RF",
                "champion_source": "BOOTSTRAP_REFERENCE",
                "action": "KEEP",
                "improvement_pct": 0.29,
                "minimum_improvement_pct": 1.0,
                "guardrail_pass": False,
                "reason_code": "KEEP_THRESHOLD_AND_GUARDRAIL",
                "reasons": ["MINIMUM_IMPROVEMENT_NOT_MET"],
                "guardrails": [{"name": "WITHIN_2_DROP", "pass": False}],
                "policy": {"minimum_improvement_pct": 1.0},
                "created_at": datetime(2026, 9, 7, 12, 0, 0),
            }
        ]

    def rankings_for_training_run(self, run_id: str):
        return [
            {
                "recommendation_id": f"REC_{RUN_ID}_H1",
                "candidate_id": f"{RUN_ID}_H1_SVR",
                "horizon": 1,
                "rank_no": 1,
                "is_best_candidate": True,
                "mae": 2.2481,
                "rmse": 3.1,
                "wape": 4.4,
                "r2": 0.2,
                "bias": -0.1,
                "p90_abs_error": 5.0,
                "max_abs_error": 8.0,
                "within_2_rate": 0.51,
                "underprediction_rate": 0.4,
                "underprediction_mae": 2.1,
            }
        ]


def _client(*, service=None, launcher=None, repo=None) -> TestClient:
    app = create_app()
    if service is not None:
        app.dependency_overrides[get_training_job_service] = lambda: service
    if launcher is not None:
        app.dependency_overrides[get_training_job_launcher] = lambda: launcher
    if repo is not None:
        app.dependency_overrides[get_read_repository] = lambda: repo
    return TestClient(app)


def test_openapi_contains_training_api_routes():
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert "/training/start" in paths
    assert "/training/status/{job_id}" in paths
    assert "/training/runs" in paths
    assert "/training/results/{run_id}" in paths


def test_training_start_returns_202_and_launches_worker_once():
    service = FakeTrainingJobService()
    launcher = FakeTrainingJobLauncher()
    client = _client(service=service, launcher=launcher)

    response = client.post(
        "/training/start",
        json={"requested_by": "operator", "random_seed": 42},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert response.json()["reused"] is False
    assert launcher.launched == [JOB_ID]
    assert service.start_calls == [("operator", 42)]


def test_training_start_reuses_completed_job_and_does_not_launch_worker():
    service = FakeTrainingJobService(reused=True)
    launcher = FakeTrainingJobLauncher()
    client = _client(service=service, launcher=launcher)

    response = client.post("/training/start")

    assert response.status_code == 202
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["training_run_id"] == RUN_ID
    assert response.json()["reused"] is True
    assert launcher.launched == []


def test_training_start_maps_no_data_ready_to_409():
    client = _client(
        service=FakeTrainingJobService(no_data=True),
        launcher=FakeTrainingJobLauncher(),
    )

    response = client.post("/training/start")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRAINING_DATA_NOT_READY"


def test_training_start_worker_launch_failure_is_persisted_and_returns_500():
    service = FakeTrainingJobService()
    launcher = FakeTrainingJobLauncher(fail=True)
    client = _client(service=service, launcher=launcher)

    response = client.post("/training/start")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "TRAINING_WORKER_LAUNCH_FAILED"
    assert service.launch_failures == [(JOB_ID, "OSError")]


def test_training_start_rejects_negative_seed_before_service_call():
    service = FakeTrainingJobService()
    client = _client(service=service, launcher=FakeTrainingJobLauncher())

    response = client.post("/training/start", json={"random_seed": -1})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.start_calls == []


def test_training_status_returns_persistent_job_contract():
    client = _client(repo=FakeTrainingReadRepository())

    response = client.get(f"/training/status/{JOB_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["training_run_id"] == RUN_ID
    assert body["source_pipeline_run_id"] == "DAY_TEST"


def test_training_status_unknown_job_returns_404():
    client = _client(repo=FakeTrainingReadRepository())

    response = client.get("/training/status/TJOB_MISSING")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRAINING_JOB_NOT_FOUND"


def test_training_runs_returns_scientific_training_run_history():
    client = _client(repo=FakeTrainingReadRepository())

    response = client.get("/training/runs?status=COMPLETED&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["rows"][0]["run_id"] == RUN_ID
    assert body["rows"][0]["completed_candidate_count"] == 8
    assert body["rows"][0]["row_count"] == 704


def test_training_results_exposes_candidates_department_metrics_and_recommendation():
    client = _client(repo=FakeTrainingReadRepository())

    response = client.get(f"/training/results/{RUN_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "COMPLETED"
    assert body["candidates"][0]["model_family"] == "RF"
    assert body["department_metrics"][0]["department_id"] == 343
    assert body["recommendations"][0]["action"] == "KEEP"
    assert body["rankings"][0]["rank_no"] == 1


def test_training_results_unknown_run_returns_404():
    client = _client(repo=FakeTrainingReadRepository())

    response = client.get("/training/results/TRN_MISSING")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRAINING_RUN_NOT_FOUND"