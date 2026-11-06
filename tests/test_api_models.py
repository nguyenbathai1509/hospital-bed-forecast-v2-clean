from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import (
    get_model_command_service,
    get_read_repository,
)


RUN_ID = "TRN_20260907T105913Z_686E6A0C"
H1_RF = f"{RUN_ID}_H1_RF"
H3_SVR = f"{RUN_ID}_H3_SVR"


class FakeModelReadRepository:
    def model_candidates(
        self,
        *,
        run_id,
        horizon,
        model_family,
        registry_status,
        is_recommended,
        limit,
        offset,
    ):
        rows = [
            {
                "candidate_id": H1_RF,
                "run_id": RUN_ID,
                "horizon": 1,
                "model_family": "RF",
                "scope": "GLOBAL",
                "registry_status": "PRODUCTION",
                "is_recommended": True,
                "artifact_type": "SKLEARN_JOBLIB",
                "inference_type": "TABULAR_28",
                "feature_version": "v2.0",
                "data_version": "excel-sha256:test",
                "mae": 2.2548,
                "rmse": 2.8586,
                "wape": 4.8975,
                "r2": 0.64,
                "bias": -0.76,
                "p90_abs_error": 4.55,
                "max_abs_error": 7.48,
                "within_2_rate": 0.59,
                "underprediction_rate": 0.44,
                "underprediction_mae": 1.66,
                "created_at": datetime(2026, 9, 7, 11, 0, 0),
                "updated_at": datetime(2026, 9, 7, 13, 50, 44),
            },
            {
                "candidate_id": H3_SVR,
                "run_id": RUN_ID,
                "horizon": 3,
                "model_family": "SVR",
                "scope": "GLOBAL",
                "registry_status": "PRODUCTION",
                "is_recommended": True,
                "artifact_type": "SKLEARN_JOBLIB",
                "inference_type": "TABULAR_28",
                "feature_version": "v2.0",
                "data_version": "excel-sha256:test",
                "mae": 2.2094,
                "rmse": 2.9271,
                "wape": 4.7988,
                "r2": 0.62,
                "bias": -0.73,
                "p90_abs_error": 4.45,
                "max_abs_error": 10.96,
                "within_2_rate": 0.56,
                "underprediction_rate": 0.37,
                "underprediction_mae": 1.94,
                "created_at": datetime(2026, 9, 7, 11, 0, 0),
                "updated_at": datetime(2026, 9, 7, 13, 50, 44),
            },
        ]

        if run_id is not None:
            rows = [row for row in rows if row["run_id"] == run_id]
        if horizon is not None:
            rows = [row for row in rows if row["horizon"] == horizon]
        if model_family is not None:
            rows = [row for row in rows if row["model_family"] == model_family]
        if registry_status is not None:
            rows = [row for row in rows if row["registry_status"] == registry_status]
        if is_recommended is not None:
            rows = [row for row in rows if row["is_recommended"] is is_recommended]

        return rows[offset : offset + limit]

    def latest_data_ready_business_date(self):
        return date(2026, 6, 30)

    def current_production_slots(self, horizon: int):
        candidate_id = H1_RF if horizon == 1 else H3_SVR
        family = "RF" if horizon == 1 else "SVR"
        return [
            {
                "production_id": horizon,
                "horizon": horizon,
                "candidate_id": candidate_id,
                "model_family": family,
                "slot_status": "ACTIVE",
                "registry_status": "PRODUCTION",
                "is_recommended": True,
                "mae": 2.25 if horizon == 1 else 2.20,
                "effective_from_business_date": date(2026, 6, 30),
                "effective_to_business_date": None,
                "promoted_by": "manual",
                "promotion_reason": "Initial verified promotion.",
                "created_at": datetime(2026, 9, 7, 13, 50, 44),
            }
        ]

    def daily_model_lock(self, origin_date, horizon: int):
        candidate_id = H1_RF if horizon == 1 else H3_SVR
        family = "RF" if horizon == 1 else "SVR"
        return {
            "origin_date": origin_date,
            "horizon": horizon,
            "model_candidate_id": candidate_id,
            "model_family": family,
            "trigger_department_id": 343,
            "locked_at": datetime(2026, 9, 7, 15, 40, 29),
        }

    def latest_recommendation_for_horizon(self, horizon: int):
        candidate_id = H1_RF if horizon == 1 else H3_SVR
        family = "RF" if horizon == 1 else "SVR"
        return {
            "recommendation_id": f"REC_{RUN_ID}_H{horizon}",
            "horizon": horizon,
            "recommended_candidate_id": candidate_id,
            "recommended_family": family,
            "action": "KEEP",
            "guardrail_pass": horizon == 3,
            "created_at": datetime(2026, 9, 7, 13, 11, 46),
        }

    def normal_production_change_exists(self, business_date):
        return business_date == date(2026, 6, 30)


class FakeModelCommandService:
    def __init__(self, *, promote_result=None, rollback_result=None, promote_exc=None, rollback_exc=None):
        self.promote_result = promote_result
        self.rollback_result = rollback_result
        self.promote_exc = promote_exc
        self.rollback_exc = rollback_exc
        self.promote_calls = []
        self.rollback_calls = []

    def promote(self, *, horizons, confirmation, requested_by, reason):
        self.promote_calls.append((horizons, confirmation, requested_by, reason))
        if self.promote_exc is not None:
            raise self.promote_exc
        return self.promote_result

    def rollback(self, *, horizon, confirmation, requested_by, reason):
        self.rollback_calls.append((horizon, confirmation, requested_by, reason))
        if self.rollback_exc is not None:
            raise self.rollback_exc
        return self.rollback_result


def _plan(*, kind="NORMAL_PROMOTION", phrase="I_CONFIRM_PROMOTION"):
    return {
        "business_date": "2026-06-30",
        "change_kind": kind,
        "quota_used": True,
        "has_changes": True,
        "confirmation_phrase": phrase,
        "items": [
            {
                "horizon": 1,
                "from_candidate_id": H1_RF,
                "from_model_family": "RF",
                "to_candidate_id": f"{RUN_ID}_H1_SVR",
                "to_model_family": "SVR",
                "to_mae": 2.2481,
                "recommendation_id": f"REC_{RUN_ID}_H1" if kind == "NORMAL_PROMOTION" else None,
                "recommendation_action": "PROMOTE" if kind == "NORMAL_PROMOTION" else None,
                "effect": "NEXT_CYCLE",
                "effective_from_business_date": "2026-07-01",
                "daily_lock_present": True,
            }
        ],
    }


def _client(*, repo=None, service=None):
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_read_repository] = lambda: repo
    if service is not None:
        app.dependency_overrides[get_model_command_service] = lambda: service
    return TestClient(app)


def test_openapi_contains_model_api_routes():
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert "/models" in paths
    assert "/models/production" in paths
    assert "/models/promote" in paths
    assert "/models/rollback" in paths


def test_models_returns_registry_metrics_without_internal_artifact_path():
    client = _client(repo=FakeModelReadRepository())

    response = client.get("/models?is_recommended=true")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [row["model_family"] for row in body["rows"]] == ["RF", "SVR"]
    assert all(row["registry_status"] == "PRODUCTION" for row in body["rows"])
    assert "artifact_path" not in body["rows"][0]
    assert "artifact_sha256" not in body["rows"][0]


def test_models_filters_horizon_and_family():
    client = _client(repo=FakeModelReadRepository())

    response = client.get("/models?horizon=3&model_family=SVR")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["rows"][0]["candidate_id"] == H3_SVR


def test_models_rejects_unsupported_horizon():
    client = _client(repo=FakeModelReadRepository())

    response = client.get("/models?horizon=2")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_HORIZON_INVALID"


def test_models_rejects_invalid_registry_status_with_422():
    client = _client(repo=FakeModelReadRepository())

    response = client.get("/models?registry_status=NOT_REAL")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_production_models_returns_active_lock_recommendation_and_quota():
    client = _client(repo=FakeModelReadRepository())

    response = client.get("/models/production")

    assert response.status_code == 200
    body = response.json()
    assert body["business_date"] == "2026-06-30"
    assert body["normal_change_quota_used"] is True
    assert len(body["horizons"]) == 2
    assert body["horizons"][0]["active"]["model_family"] == "RF"
    assert body["horizons"][1]["active"]["model_family"] == "SVR"
    assert body["horizons"][0]["scheduled"] is None
    assert body["horizons"][0]["daily_lock"]["trigger_department_id"] == 343
    assert body["horizons"][0]["recommendation"]["action"] == "KEEP"


def test_promote_confirmation_required_preserves_v2_16_plan():
    service = FakeModelCommandService(
        promote_result={
            "status": "CONFIRMATION_REQUIRED",
            "message": "Review before commit.",
            "plan": _plan(),
        }
    )
    client = _client(service=service)

    response = client.post(
        "/models/promote",
        json={"horizons": [1], "requested_by": "operator"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CONFIRMATION_REQUIRED"
    assert body["plan"]["confirmation_phrase"] == "I_CONFIRM_PROMOTION"
    assert body["plan"]["items"][0]["effect"] == "NEXT_CYCLE"
    assert service.promote_calls[0][0] == [1]
    assert service.promote_calls[0][1] is None


def test_promote_completed_delegates_exact_confirmation_to_service():
    service = FakeModelCommandService(
        promote_result={
            "status": "COMPLETED",
            "change_id": "PROMOTE_TEST",
            "business_date": "2026-06-30",
            "change_kind": "NORMAL_PROMOTION",
            "items": _plan()["items"],
        }
    )
    client = _client(service=service)

    response = client.post(
        "/models/promote",
        json={
            "horizons": [1],
            "confirmation": "I_CONFIRM_PROMOTION",
            "requested_by": "operator",
            "reason": "Promote after review.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["change_id"] == "PROMOTE_TEST"
    assert service.promote_calls[0][1] == "I_CONFIRM_PROMOTION"


def test_promote_no_change_is_safe_terminal_result():
    service = FakeModelCommandService(
        promote_result={
            "status": "NO_CHANGE",
            "message": "Already active.",
            "plan": {
                **_plan(),
                "has_changes": False,
                "items": [],
            },
        }
    )
    client = _client(service=service)

    response = client.post("/models/promote")

    assert response.status_code == 200
    assert response.json()["status"] == "NO_CHANGE"
    assert response.json()["plan"]["items"] == []


def test_promote_runtime_conflict_maps_to_409_without_reimplementing_rule():
    service = FakeModelCommandService(
        promote_exc=RuntimeError("NORMAL Production Change quota already used")
    )
    client = _client(service=service)

    response = client.post("/models/promote")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_PROMOTION_CONFLICT"


def test_promote_value_error_maps_to_400():
    service = FakeModelCommandService(promote_exc=ValueError("Promotion reason is required"))
    client = _client(service=service)

    response = client.post("/models/promote", json={"reason": ""})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_PROMOTION_INVALID"


def test_rollback_confirmation_required_preserves_strong_phrase():
    service = FakeModelCommandService(
        rollback_result={
            "status": "CONFIRMATION_REQUIRED",
            "message": "Review emergency rollback.",
            "plan": _plan(
                kind="EMERGENCY_ROLLBACK",
                phrase="I_CONFIRM_EMERGENCY_ROLLBACK",
            ),
        }
    )
    client = _client(service=service)

    response = client.post(
        "/models/rollback",
        json={"horizon": 1, "reason": "Investigate model degradation."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMATION_REQUIRED"
    assert (
        response.json()["plan"]["confirmation_phrase"]
        == "I_CONFIRM_EMERGENCY_ROLLBACK"
    )
    assert service.rollback_calls[0][1] is None


def test_rollback_completed_delegates_to_v2_16_service():
    service = FakeModelCommandService(
        rollback_result={
            "status": "COMPLETED",
            "change_id": "ROLLBACK_TEST",
            "business_date": "2026-06-30",
            "change_kind": "EMERGENCY_ROLLBACK",
            "items": _plan(
                kind="EMERGENCY_ROLLBACK",
                phrase="I_CONFIRM_EMERGENCY_ROLLBACK",
            )["items"],
        }
    )
    client = _client(service=service)

    response = client.post(
        "/models/rollback",
        json={
            "horizon": 1,
            "confirmation": "I_CONFIRM_EMERGENCY_ROLLBACK",
            "requested_by": "operator",
            "reason": "Emergency rollback after verified production incident.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["change_kind"] == "EMERGENCY_ROLLBACK"
    assert service.rollback_calls[0][1] == "I_CONFIRM_EMERGENCY_ROLLBACK"


def test_rollback_unavailable_maps_existing_service_runtime_error_to_409():
    service = FakeModelCommandService(
        rollback_exc=RuntimeError("No previous RETIRED Production candidate exists for H+1")
    )
    client = _client(service=service)

    response = client.post(
        "/models/rollback",
        json={"horizon": 1, "reason": "Preview rollback availability."},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_ROLLBACK_CONFLICT"


def test_rollback_short_audit_reason_maps_v2_16_value_error_to_400():
    service = FakeModelCommandService(
        rollback_exc=ValueError(
            "Emergency rollback requires an explicit audit reason of at least 10 characters"
        )
    )
    client = _client(service=service)

    response = client.post(
        "/models/rollback",
        json={
            "horizon": 1,
            "confirmation": "I_CONFIRM_EMERGENCY_ROLLBACK",
            "reason": "short",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_ROLLBACK_INVALID"