from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_demo_reset_service
from src.demo_reset.service import (
    DemoResetBusyError,
    DemoResetConfirmationError,
    DemoResetDisabledError,
)


STATUS_RESULT = {
    "enabled": False,
    "confirmation_phrase": "RESET DEMO STATE",
    "clean": False,
    "busy": False,
    "busy_counts": {
        "pipeline_runs": 0,
        "api_training_jobs": 0,
        "training_runs": 0,
        "production_monitoring_runs": 0,
    },
    "counts": {
        "pipeline_runs": 10,
        "raw_bed_daily": 362,
    },
    "retained": {
        "departments": 2,
        "schema_migrations": 9,
    },
}


RESET_RESULT = {
    "status": "RESET_COMPLETED",
    "clean": True,
    "before": {
        "pipeline_runs": 10,
        "raw_bed_daily": 362,
    },
    "after": {
        "pipeline_runs": 0,
        "raw_bed_daily": 0,
    },
    "retained": {
        "departments": 2,
        "schema_migrations": 9,
    },
}


class FakeDemoResetService:
    def __init__(
        self,
        *,
        status_result=None,
        reset_result=None,
        reset_exc=None,
    ):
        self.status_result = (
            status_result
            if status_result is not None
            else STATUS_RESULT
        )
        self.reset_result = (
            reset_result
            if reset_result is not None
            else RESET_RESULT
        )
        self.reset_exc = reset_exc
        self.received_confirmation = None

    def status(self):
        return self.status_result

    def reset(self, *, confirmation: str):
        self.received_confirmation = confirmation

        if self.reset_exc is not None:
            raise self.reset_exc

        return self.reset_result


def client_for(service: FakeDemoResetService):
    app = create_app()

    app.dependency_overrides[
        get_demo_reset_service
    ] = lambda: service

    return TestClient(app)


def test_demo_reset_status_contract():
    service = FakeDemoResetService()

    with client_for(service) as client:
        response = client.get(
            "/demo/reset/status"
        )

    assert response.status_code == 200

    body = response.json()

    assert body["enabled"] is False
    assert body["clean"] is False
    assert body["busy"] is False

    assert body["retained"] == {
        "departments": 2,
        "schema_migrations": 9,
    }


def test_demo_reset_success_contract():
    service = FakeDemoResetService()

    with client_for(service) as client:
        response = client.post(
            "/demo/reset",
            json={
                "confirmation": "RESET DEMO STATE",
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "RESET_COMPLETED"
    assert body["clean"] is True

    assert service.received_confirmation == (
        "RESET DEMO STATE"
    )


def test_demo_reset_disabled_maps_to_403():
    service = FakeDemoResetService(
        reset_exc=DemoResetDisabledError(
            "Demo Reset disabled."
        )
    )

    with client_for(service) as client:
        response = client.post(
            "/demo/reset",
            json={
                "confirmation": "RESET DEMO STATE",
            },
        )

    assert response.status_code == 403
    assert (
        response.json()["error"]["code"]
        == "DEMO_RESET_DISABLED"
    )


def test_demo_reset_bad_confirmation_maps_to_400():
    service = FakeDemoResetService(
        reset_exc=DemoResetConfirmationError(
            "Confirmation phrase không chính xác."
        )
    )

    with client_for(service) as client:
        response = client.post(
            "/demo/reset",
            json={
                "confirmation": "SAI",
            },
        )

    assert response.status_code == 400

    assert (
        response.json()["error"]["code"]
        == "DEMO_RESET_CONFIRMATION_INVALID"
    )


def test_demo_reset_busy_maps_to_409():
    service = FakeDemoResetService(
        reset_exc=DemoResetBusyError(
            "Training đang chạy."
        )
    )

    with client_for(service) as client:
        response = client.post(
            "/demo/reset",
            json={
                "confirmation": "RESET DEMO STATE",
            },
        )

    assert response.status_code == 409

    assert (
        response.json()["error"]["code"]
        == "DEMO_RESET_BUSY"
    )
