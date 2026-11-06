import httpx
import pytest

from scripts.profile_ui import ProfilingClient, is_read_only_request


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/pipeline/run", {}), ("POST", "/training/start", {}),
    ("POST", "/models/promote", {}), ("POST", "/models/rollback", {}),
    ("POST", "/forecasts/production", {}), ("POST", "/forecasts/preview", {}),
    ("POST", "/forecasts/official/confirm", {"confirmation": "I_CONFIRM_OFFICIAL"}),
    ("POST", "/demo/reset", {}), ("POST", "/monitoring/run", {}),
    ("GET", "/unknown-route", None),
])
def test_profiler_blocks_actions_before_sending_any_request(method, path, body):
    def forbidden(request):
        raise AssertionError("Blocked operation must not reach transport")
    client = ProfilingClient("http://test", transport=httpx.MockTransport(forbidden))
    with pytest.raises(RuntimeError, match="blocks non-read-only"):
        client._request(method, path, json_body=body)


def test_profiler_allows_read_only_plan_without_confirmation():
    assert is_read_only_request("POST", "/forecasts/official/confirm", {"confirmed_by": "streamlit"})
    assert is_read_only_request("GET", "/training/results/RUN_TEST")
    assert not is_read_only_request("GET", "/training/results/../other")


def test_profiler_records_calls_but_not_sensitive_parameters_or_response():
    client = ProfilingClient("http://test", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"sensitive_result": "private"})))
    with client.request_scope():
        client.training_evaluation(run_id="PRIVATE_RUN", horizon=1, model_family="RF", department_id=343)
    assert len(client.measurements) == 1
    record = client.measurements[0]
    assert record["route"] == "/training/evaluation/{id}"
    assert record["error"] is None and record["elapsed_ms"] >= 0
    assert "PRIVATE_RUN" not in str(record) and "343" not in str(record)
    assert "private" not in str(record)
