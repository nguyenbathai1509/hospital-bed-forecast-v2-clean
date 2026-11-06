from __future__ import annotations

import json

import httpx

from app.api_client import HospitalApiClient


def test_demo_reset_status_client():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/demo/reset/status"

        return httpx.Response(
            200,
            json={
                "enabled": False,
                "confirmation_phrase": "RESET DEMO STATE",
                "clean": False,
                "busy": False,
                "busy_counts": {},
                "counts": {
                    "pipeline_runs": 10,
                },
                "retained": {
                    "departments": 2,
                    "schema_migrations": 9,
                },
            },
        )

    client = HospitalApiClient(
        "http://test",
        transport=httpx.MockTransport(handler),
    )

    result = client.demo_reset_status()

    assert result["enabled"] is False
    assert result["clean"] is False
    assert result["counts"]["pipeline_runs"] == 10


def test_reset_demo_client_posts_confirmation():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/demo/reset"

        payload = json.loads(
            request.content.decode("utf-8")
        )

        assert payload == {
            "confirmation": "RESET DEMO STATE",
        }

        return httpx.Response(
            200,
            json={
                "status": "RESET_COMPLETED",
                "clean": True,
                "before": {
                    "pipeline_runs": 10,
                },
                "after": {
                    "pipeline_runs": 0,
                },
                "retained": {
                    "departments": 2,
                    "schema_migrations": 9,
                },
            },
        )

    client = HospitalApiClient(
        "http://test",
        transport=httpx.MockTransport(handler),
    )

    result = client.reset_demo(
        confirmation="RESET DEMO STATE",
    )

    assert result["status"] == "RESET_COMPLETED"
    assert result["clean"] is True
