from __future__ import annotations

import json

import httpx
import pytest

from app.api_client import ApiClientError, HospitalApiClient


def make_client(handler):
    return HospitalApiClient(
        "http://testserver",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def json_response(data, status_code=200):
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(data).encode("utf-8"),
    )


def test_health_calls_fastapi_only():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/health"
        return json_response({"status": "OK", "service": "hospital-bed-forecast-v2", "api_version": "v2"})

    assert make_client(handler).health()["status"] == "OK"


def test_history_sends_department_and_dates():
    def handler(request):
        params = dict(request.url.params)
        assert request.url.path == "/history"
        assert params["department_id"] == "343"
        assert params["start_date"] == "2026-06-01"
        assert params["end_date"] == "2026-06-30"
        return json_response({"department_id": 343, "count": 0, "limit": 500, "offset": 0, "rows": []})

    make_client(handler).history(
        department_id=343,
        start_date="2026-06-01",
        end_date="2026-06-30",
    )


def test_training_start_uses_async_api_contract():
    def handler(request):
        assert request.url.path == "/training/start"
        body = json.loads(request.content)
        assert body == {"requested_by": "streamlit", "random_seed": 42}
        return json_response(
            {
                "job_id": "TJOB_TEST",
                "status": "PENDING",
                "business_date": "2026-06-30",
                "source_pipeline_run_id": "DAY_TEST",
                "training_run_id": None,
                "reused": False,
            },
            202,
        )

    result = make_client(handler).start_training()
    assert result["job_id"] == "TJOB_TEST"


def test_models_query_keeps_registry_filters_in_http_layer():
    def handler(request):
        params = dict(request.url.params)
        assert request.url.path == "/models"
        assert params["horizon"] == "1"
        assert params["model_family"] == "RF"
        assert params["registry_status"] == "PRODUCTION"
        assert params["is_recommended"] == "true"
        return json_response({"count": 0, "limit": 200, "offset": 0, "rows": []})

    make_client(handler).models(
        horizon=1,
        model_family="RF",
        registry_status="PRODUCTION",
        is_recommended=True,
    )


def test_promotion_preview_omits_confirmation_when_not_supplied():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/models/promote"
        assert "confirmation" not in body
        assert body["horizons"] == [1, 3]
        return json_response({"status": "NO_CHANGE", "items": [], "plan": None})

    make_client(handler).promote_models(
        horizons=[1, 3],
        requested_by="streamlit",
        reason="preview",
    )


def test_promotion_commit_preserves_exact_confirmation_phrase():
    def handler(request):
        body = json.loads(request.content)
        assert body["confirmation"] == "I_CONFIRM_PROMOTION"
        return json_response({"status": "COMPLETED", "items": [], "plan": None})

    make_client(handler).promote_models(
        horizons=[1],
        requested_by="streamlit",
        reason="approved change",
        confirmation="I_CONFIRM_PROMOTION",
    )


def test_forecast_preview_marks_custom_candidate_by_horizon_string_key():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/forecasts/preview"
        assert body["mode"] == "CUSTOM"
        assert body["department_ids"] == [343]
        assert body["horizons"] == [1]
        assert body["custom_candidates"] == {"1": "CAND_H1"}
        return json_response(
            {
                "status": "PREVIEW",
                "persisted": False,
                "official": False,
                "monitoring_eligible": False,
                "mode": "CUSTOM",
                "origin_date": "2026-06-30",
                "prediction_count": 0,
                "predictions": [],
            }
        )

    make_client(handler).forecast_preview(
        mode="CUSTOM",
        origin_date="2026-06-30",
        department_ids=[343],
        horizons=[1],
        custom_candidates={"1": "CAND_H1"},
    )


def test_official_confirmation_preserves_exact_strong_phrase():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/forecasts/official/confirm"
        assert body["confirmation"] == "I_CONFIRM_OFFICIAL"
        return json_response(
            {
                "status": "COMPLETED",
                "origin_date": "2026-06-30",
                "drafts": [],
                "official_count": 0,
                "results": [],
            }
        )

    make_client(handler).confirm_official(
        origin_date="2026-06-30",
        confirmed_by="streamlit",
        confirmation="I_CONFIRM_OFFICIAL",
    )


def test_monitoring_run_delegates_pipeline_id():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/monitoring/run"
        assert body == {"pipeline_run_id": "DAY_TEST"}
        return json_response(
            {
                "status": "WAITING_FOR_ACTUAL",
                "monitoring_run_id": "MON_TEST",
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

    result = make_client(handler).run_monitoring("DAY_TEST")
    assert result["pipeline_run_id"] == "DAY_TEST"


def test_api_problem_json_is_mapped_to_typed_error():
    def handler(request):
        return json_response(
            {
                "error": {
                    "code": "MODEL_ROLLBACK_CONFLICT",
                    "message": "No previous RETIRED Production candidate exists for H+1",
                    "details": None,
                }
            },
            409,
        )

    with pytest.raises(ApiClientError) as captured:
        make_client(handler).rollback_model(
            horizon=1,
            requested_by="streamlit",
            reason="runtime preview",
        )

    assert captured.value.status_code == 409
    assert captured.value.code == "MODEL_ROLLBACK_CONFLICT"


def test_unreachable_api_becomes_api_unreachable():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(ApiClientError) as captured:
        make_client(handler).health()

    assert captured.value.code == "API_UNREACHABLE"
    assert captured.value.status_code is None


@pytest.mark.parametrize("exception_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout])
def test_timeout_is_distinct_and_never_retries_a_mutation(exception_type):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception_type("timeout", request=request)

    with pytest.raises(ApiClientError) as captured:
        make_client(handler).run_pipeline()
    assert captured.value.code == "API_TIMEOUT"
    assert "trước khi gửi lại" in captured.value.message
    assert len(calls) == 1


def test_success_with_invalid_json_is_a_displayable_error():
    def handler(request):
        return httpx.Response(200, text="<html>proxy error</html>")

    with pytest.raises(ApiClientError) as captured:
        make_client(handler).health()
    assert captured.value.code == "API_INVALID_RESPONSE"
    assert captured.value.status_code == 200


def test_non_json_server_error_is_still_a_displayable_error():
    with pytest.raises(ApiClientError) as captured:
        make_client(lambda request: httpx.Response(503, text="Unavailable")).health()
    assert captured.value.code == "API_ERROR"
    assert captured.value.status_code == 503


def test_training_evaluation_sends_run_model_horizon_and_department_filters():
    def handler(request):
        params = dict(request.url.params)
        assert request.url.path == "/training/evaluation/TRN_TEST"
        assert params == {
            "horizon": "1",
            "model_family": "RF",
            "department_id": "343",
        }
        return json_response(
            {
                "run_id": "TRN_TEST",
                "horizon": 1,
                "model_family": "RF",
                "department_id": 343,
                "split": {
                    "train_start": "2026-01-04",
                    "train_end": "2026-04-26",
                    "validation_start": "2026-04-27",
                    "validation_end": "2026-05-24",
                    "test_start": "2026-05-25",
                    "test_end": "2026-06-30",
                },
                "count": 0,
                "rows": [],
            }
        )

    result = make_client(handler).training_evaluation(
        run_id="TRN_TEST",
        horizon=1,
        model_family="RF",
        department_id=343,
    )
    assert result["run_id"] == "TRN_TEST"
