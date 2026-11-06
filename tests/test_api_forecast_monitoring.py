from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.forecast_commands import MonitoringCommandService
from src.api.dependencies import (
    get_forecast_command_service,
    get_monitoring_command_service,
    get_read_repository,
)

RUN_ID = "TRN_20260907T105913Z_686E6A0C"
H1_RF = f"{RUN_ID}_H1_RF"
H3_SVR = f"{RUN_ID}_H3_SVR"


def prediction(horizon=1, department_id=343, family="RF", candidate_id=H1_RF):
    return {
        "origin_date": "2026-06-30",
        "department_id": department_id,
        "horizon": horizon,
        "target_date": "2026-07-01" if horizon == 1 else "2026-07-03",
        "candidate_id": candidate_id,
        "model_family": family,
        "source_mode": "PRODUCTION",
        "feature_version": "v2.0",
        "data_version": "excel-sha256:test",
        "prediction_raw": 46.9,
        "prediction_rounded": 47,
        "planned_beds": 55,
        "predicted_utilization_pct": 85.3,
        "capacity_alert": False,
        "capacity_excess_beds": 0,
    }


def draft():
    return {
        "draft_id": "DRF_TEST",
        **prediction(),
        "status": "DRAFT",
        "created_by": "api",
        "created_at": datetime(2026, 9, 8, 8, 0, 0),
        "confirmed_at": None,
    }


def official():
    row = prediction()
    row.pop("source_mode")
    return {
        "official_id": "OFF_TEST",
        "source_draft_id": "DRF_TEST",
        **row,
        "confirmed_by": "manual",
        "issued_at": datetime(2026, 9, 8, 8, 1, 0),
    }


class FakeForecastService:
    def __init__(
        self,
        preview_result=None,
        production_result=None,
        confirm_result=None,
        exc=None,
    ):
        self.preview_result = preview_result
        self.production_result = production_result
        self.confirm_result = confirm_result
        self.exc = exc
        self.calls = []

    def preview(self, **kwargs):
        self.calls.append(("preview", kwargs))
        if self.exc:
            raise self.exc
        return self.preview_result

    def production_predict(self, **kwargs):
        self.calls.append(("production", kwargs))
        if self.exc:
            raise self.exc
        return self.production_result

    def confirm_official(self, **kwargs):
        self.calls.append(("confirm", kwargs))
        if self.exc:
            raise self.exc
        return self.confirm_result


class FakeMonitoringService:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def run(self, *, pipeline_run_id=None):
        self.calls.append(pipeline_run_id)
        if self.exc:
            raise self.exc
        return self.result


class FakeReadRepo:
    def forecast_drafts(self, **kwargs):
        return [draft()]

    def official_forecasts(self, **kwargs):
        return [official()]

    def latest_monitoring_run(self):
        return {
            "monitoring_run_id": "MON_DAY_TEST",
            "pipeline_run_id": "DAY_TEST",
            "business_date": date(2026, 6, 30),
            "latest_actual_date": date(2026, 6, 30),
            "status": "WAITING_FOR_ACTUAL",
            "official_total_count": 4,
            "matched_total_count": 0,
            "waiting_for_actual_count": 4,
            "missing_actual_count": 0,
            "metric_row_count": 0,
            "started_at": datetime(2026, 9, 8, 8, 0, 0),
            "completed_at": datetime(2026, 9, 8, 8, 0, 1),
        }

    def monitoring_metrics(self, monitoring_run_id):
        return []


def client(*, forecast=None, monitoring=None, repo=None):
    app = create_app()

    if forecast is not None:
        app.dependency_overrides[
            get_forecast_command_service
        ] = lambda: forecast

    if monitoring is not None:
        app.dependency_overrides[
            get_monitoring_command_service
        ] = lambda: monitoring

    if repo is not None:
        app.dependency_overrides[
            get_read_repository
        ] = lambda: repo

    return TestClient(app)


def test_openapi_has_part_d_routes():
    paths = create_app().openapi()["paths"]

    for path in (
        "/forecasts/preview",
        "/forecasts/production",
        "/forecasts/drafts",
        "/forecasts/official/confirm",
        "/forecasts/official",
        "/monitoring",
        "/monitoring/run",
    ):
        assert path in paths


def test_preview_is_explicitly_non_persisted_non_official():
    service = FakeForecastService(
        preview_result={
            "status": "PREVIEW",
            "persisted": False,
            "official": False,
            "monitoring_eligible": False,
            "mode": "PRODUCTION",
            "origin_date": "2026-06-30",
            "prediction_count": 1,
            "predictions": [prediction()],
        }
    )

    response = client(
        forecast=service
    ).post(
        "/forecasts/preview",
        json={"mode": "PRODUCTION"},
    )

    assert response.status_code == 200

    body = response.json()

    assert body["persisted"] is False
    assert body["official"] is False
    assert body["monitoring_eligible"] is False
    assert body["generated_at"] is not None
    assert body["generated_at"].endswith(("Z", "+00:00"))


def test_custom_preview_delegates_candidate_map():
    service = FakeForecastService(
        preview_result={
            "status": "PREVIEW",
            "persisted": False,
            "official": False,
            "monitoring_eligible": False,
            "mode": "CUSTOM",
            "origin_date": "2026-06-30",
            "prediction_count": 1,
            "predictions": [
                {
                    **prediction(),
                    "source_mode": "CUSTOM",
                }
            ],
        }
    )

    response = client(
        forecast=service
    ).post(
        "/forecasts/preview",
        json={
            "mode": "CUSTOM",
            "horizons": [1],
            "custom_candidates": {
                "1": H1_RF
            },
        },
    )

    assert response.status_code == 200

    assert (
        service.calls[0][1]["custom_candidates"]
        == {1: H1_RF}
    )


def test_preview_value_error_maps_400():
    response = client(
        forecast=FakeForecastService(
            exc=ValueError("bad preview")
        )
    ).post(
        "/forecasts/preview",
        json={"mode": "PRODUCTION"},
    )

    assert response.status_code == 400

    assert (
        response.json()["error"]["code"]
        == "FORECAST_PREVIEW_INVALID"
    )


def test_production_predict_returns_draft_only_contract():
    service = FakeForecastService(
        production_result={
            "status": "DRAFT_READY",
            "origin_date": "2026-06-30",
            "created_count": 1,
            "reused_count": 0,
            "skipped_official_count": 0,
            "created": [draft()],
            "reused": [],
            "skipped_official": [],
        }
    )

    response = client(
        forecast=service
    ).post(
        "/forecasts/production",
        json={"horizons": [1]},
    )

    assert response.status_code == 200

    assert (
        response.json()["created"][0]["status"]
        == "DRAFT"
    )

    assert (
        "official_id"
        not in response.json()["created"][0]
    )


def test_production_predict_conflict_maps_409():
    response = client(
        forecast=FakeForecastService(
            exc=RuntimeError("lock changed")
        )
    ).post(
        "/forecasts/production",
        json={},
    )

    assert response.status_code == 409

    assert (
        response.json()["error"]["code"]
        == "FORECAST_PRODUCTION_CONFLICT"
    )


def test_list_drafts_read_model():
    response = client(
        repo=FakeReadRepo()
    ).get(
        "/forecasts/drafts"
        "?origin_date=2026-06-30"
        "&status=DRAFT"
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1

    assert (
        response.json()["rows"][0]["draft_id"]
        == "DRF_TEST"
    )


def test_official_confirmation_without_phrase_is_read_only_plan():
    service = FakeForecastService(
        confirm_result={
            "status": "CONFIRMATION_REQUIRED",
            "origin_date": "2026-06-30",
            "confirmation_phrase": "I_CONFIRM_OFFICIAL",
            "draft_count": 1,
            "drafts": [draft()],
        }
    )

    response = client(
        forecast=service
    ).post(
        "/forecasts/official/confirm",
        json={},
    )

    assert response.status_code == 200

    assert (
        response.json()["status"]
        == "CONFIRMATION_REQUIRED"
    )

    assert (
        response.json()["draft_count"]
        == 1
    )


def test_official_confirmation_completed_contract():
    service = FakeForecastService(
        confirm_result={
            "status": "COMPLETED",
            "origin_date": "2026-06-30",
            "official_count": 1,
            "results": [
                {
                    "status": "OFFICIAL",
                    "draft_id": "DRF_TEST",
                    "official_id": "OFF_TEST",
                    "origin_date": "2026-06-30",
                    "department_id": 343,
                    "horizon": 1,
                    "candidate_id": H1_RF,
                    "prediction_raw": 46.9,
                    "prediction_rounded": 47,
                }
            ],
        }
    )

    response = client(
        forecast=service
    ).post(
        "/forecasts/official/confirm",
        json={
            "confirmation":
                "I_CONFIRM_OFFICIAL"
        },
    )

    assert response.status_code == 200

    assert (
        response.json()["official_count"]
        == 1
    )


def test_official_conflict_maps_409():
    response = client(
        forecast=FakeForecastService(
            exc=RuntimeError("stale lock")
        )
    ).post(
        "/forecasts/official/confirm",
        json={
            "confirmation":
                "I_CONFIRM_OFFICIAL"
        },
    )

    assert response.status_code == 409

    assert (
        response.json()["error"]["code"]
        == "FORECAST_OFFICIAL_CONFLICT"
    )


def test_list_officials_read_model():
    response = client(
        repo=FakeReadRepo()
    ).get(
        "/forecasts/official"
        "?origin_date=2026-06-30"
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1

    assert (
        response.json()["rows"][0]["official_id"]
        == "OFF_TEST"
    )


def test_monitoring_get_is_official_only_snapshot():
    response = client(
        repo=FakeReadRepo()
    ).get(
        "/monitoring"
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["run"]["status"]
        == "WAITING_FOR_ACTUAL"
    )

    assert (
        body["run"]["official_total_count"]
        == 4
    )

    assert body["metrics"] == []


def test_monitoring_get_handles_no_run():
    class EmptyRepo(FakeReadRepo):
        def latest_monitoring_run(self):
            return None

    response = client(
        repo=EmptyRepo()
    ).get(
        "/monitoring"
    )

    assert response.status_code == 200

    assert response.json() == {
        "run": None,
        "metrics": [],
    }


def test_real_monitoring_command_adapter_unwraps_production_monitoring(
    monkeypatch,
):
    expected = {
        "status": "WAITING_FOR_ACTUAL",
        "monitoring_run_id": "MON_DAY_TEST",
        "pipeline_run_id": "DAY_TEST",
        "business_date": "2026-06-30",
        "latest_actual_date": "2026-06-30",
        "official_total_count": 4,
        "matched_total_count": 0,
        "waiting_for_actual_count": 4,
        "missing_actual_count": 0,
        "metric_row_count": 0,
        "metrics": [],
    }

    def fake_cycle(
        *,
        pipeline_run_id=None,
    ):
        assert (
            pipeline_run_id
            == "DAY_TEST"
        )

        return {
            "status":
                "WAITING_FOR_ACTUAL",
            "actual_matching": {
                "status":
                    "WAITING_FOR_ACTUAL"
            },
            "production_monitoring":
                expected,
        }

    monkeypatch.setattr(
        "src.api.forecast_commands."
        "run_monitoring_cycle",
        fake_cycle,
    )

    result = (
        MonitoringCommandService()
        .run(
            pipeline_run_id="DAY_TEST"
        )
    )

    assert result == expected


def test_monitoring_run_delegates_pipeline_id():
    service = FakeMonitoringService(
        result={
            "status": "WAITING_FOR_ACTUAL",
            "monitoring_run_id": "MON_DAY_TEST",
            "pipeline_run_id": "DAY_TEST",
            "business_date": "2026-06-30",
            "latest_actual_date": "2026-06-30",
            "official_total_count": 4,
            "matched_total_count": 0,
            "waiting_for_actual_count": 4,
            "missing_actual_count": 0,
            "metric_row_count": 0,
            "metrics": [],
        }
    )

    response = client(
        monitoring=service
    ).post(
        "/monitoring/run",
        json={
            "pipeline_run_id":
                "DAY_TEST"
        },
    )

    assert response.status_code == 200
    assert service.calls == ["DAY_TEST"]

    assert (
        response.json()["metric_row_count"]
        == 0
    )


def test_monitoring_conflict_maps_409():
    response = client(
        monitoring=FakeMonitoringService(
            exc=RuntimeError(
                "missing pipeline"
            )
        )
    ).post(
        "/monitoring/run",
        json={},
    )

    assert response.status_code == 409

    assert (
        response.json()["error"]["code"]
        == "MONITORING_CONFLICT"
    )
