from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_read_repository

RUN_ID = "TRN_TEST"


class FakeEvaluationRepo:
    def __init__(self, *, has_run: bool = True, has_rows: bool = True):
        self.has_run = has_run
        self.has_rows = has_rows
        self.calls = []

    def training_run(self, run_id: str):
        if not self.has_run or run_id != RUN_ID:
            return None
        return {
            "run_id": RUN_ID,
            "status": "COMPLETED",
        }

    def training_evaluation_split(self, run_id: str):
        assert run_id == RUN_ID
        return {
            "train_start": date(2026, 1, 4),
            "train_end": date(2026, 4, 26),
            "validation_start": date(2026, 4, 27),
            "validation_end": date(2026, 5, 24),
            "test_start": date(2026, 5, 25),
            "test_end": date(2026, 6, 30),
        }

    def training_evaluation_rows(
        self,
        *,
        run_id: str,
        horizon: int,
        model_family: str,
        department_id: int | None,
    ):
        self.calls.append((run_id, horizon, model_family, department_id))
        if not self.has_rows:
            return []
        return [
            {
                "candidate_id": f"{RUN_ID}_H1_RF",
                "run_id": RUN_ID,
                "horizon": 1,
                "model_family": "RF",
                "department_id": 343,
                "origin_date": date(2026, 5, 24),
                "target_date": date(2026, 5, 25),
                "actual_occupied_beds": 51.0,
                "prediction_raw": 49.8,
                "residual": 1.2,
                "absolute_error": 1.2,
            }
        ]


def client(repo) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_read_repository] = lambda: repo
    return TestClient(app)


def test_openapi_contains_training_evaluation_route():
    paths = create_app().openapi()["paths"]
    assert "/training/evaluation/{run_id}" in paths


def test_training_evaluation_returns_split_and_row_level_test_evidence():
    repo = FakeEvaluationRepo()
    response = client(repo).get(
        f"/training/evaluation/{RUN_ID}",
        params={
            "horizon": 1,
            "model_family": "RF",
            "department_id": 343,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["split"]["test_start"] == "2026-05-25"
    assert body["split"]["test_end"] == "2026-06-30"
    assert body["rows"][0]["actual_occupied_beds"] == 51.0
    assert body["rows"][0]["prediction_raw"] == 49.8
    assert body["rows"][0]["residual"] == 1.2
    assert repo.calls == [(RUN_ID, 1, "RF", 343)]


def test_training_evaluation_rejects_horizon_2():
    response = client(FakeEvaluationRepo()).get(
        f"/training/evaluation/{RUN_ID}",
        params={"horizon": 2, "model_family": "RF"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TRAINING_EVALUATION_HORIZON_INVALID"


def test_training_evaluation_returns_404_when_run_does_not_exist():
    response = client(FakeEvaluationRepo(has_run=False)).get(
        "/training/evaluation/MISSING",
        params={"horizon": 1, "model_family": "RF"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRAINING_RUN_NOT_FOUND"


def test_training_evaluation_returns_404_when_evidence_is_missing():
    response = client(FakeEvaluationRepo(has_rows=False)).get(
        f"/training/evaluation/{RUN_ID}",
        params={"horizon": 1, "model_family": "RF", "department_id": 343},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRAINING_EVALUATION_NOT_FOUND"