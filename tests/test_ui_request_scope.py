from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.api_client import ApiClientError, HospitalApiClient


def client_with_sessions(monkeypatch, handler):
    client = HospitalApiClient("http://testserver", transport=httpx.MockTransport(handler))
    sessions = []
    factory = client._new_http_client

    def create():
        session = factory()
        sessions.append(session)
        return session

    monkeypatch.setattr(client, "_new_http_client", create)
    return client, sessions


def test_scope_reuses_one_connection_but_never_caches_responses(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"version": len(requests)})

    client, sessions = client_with_sessions(monkeypatch, handle)
    with client.request_scope():
        assert client.health()["version"] == 1
        assert client.health()["version"] == 2
        assert len(sessions) == 1 and not sessions[0].is_closed
    assert sessions[0].is_closed
    with client.request_scope():
        assert client.health()["version"] == 3
    assert len(sessions) == 2 and all(session.is_closed for session in sessions)


def test_nested_scope_does_not_close_outer_connection(monkeypatch):
    client, sessions = client_with_sessions(monkeypatch, lambda r: httpx.Response(200, json={}))
    with client.request_scope():
        client.health()
        with client.request_scope():
            client.health()
        assert not sessions[0].is_closed
        client.health()
    assert len(sessions) == 1 and sessions[0].is_closed


@pytest.mark.parametrize("error", [RuntimeError, BaseException])
def test_scope_closes_and_resets_even_when_render_is_interrupted(monkeypatch, error):
    client, sessions = client_with_sessions(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(error):
        with client.request_scope():
            client.health()
            raise error("simulate render interruption")
    assert sessions[0].is_closed
    client.health()  # Outside the scope must create a fresh, short-lived connection.
    assert len(sessions) == 2 and sessions[1].is_closed


def test_timeout_within_scope_does_not_retry_or_prevent_fresh_read(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("unknown outcome", request=request)
        return httpx.Response(200, json={"status": "OK"})

    client, sessions = client_with_sessions(monkeypatch, handle)
    with client.request_scope():
        with pytest.raises(ApiClientError, match="thời gian chờ"):
            client.run_pipeline()
        assert client.health()["status"] == "OK"
    assert calls == ["POST", "GET"]
    assert len(sessions) == 1 and sessions[0].is_closed


def test_shared_presentation_client_isolates_concurrent_render_cookies(monkeypatch):
    barrier = Barrier(2)

    def handle(request):
        owner = request.url.params.get("owner")
        if owner:
            assert "cookie" not in request.headers
            return httpx.Response(200, json={}, headers={"set-cookie": f"render_owner={owner}; Path=/"})
        return httpx.Response(200, json={"cookie": request.headers.get("cookie")})

    client, sessions = client_with_sessions(monkeypatch, handle)

    def render(owner):
        with client.request_scope():
            client._request("GET", "/health", params={"owner": owner})
            barrier.wait(timeout=5)
            return client.health()["cookie"]

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(render, ("one", "two"))) == ["render_owner=one", "render_owner=two"]
    assert len(sessions) == 2 and all(session.is_closed for session in sessions)
    with client.request_scope():
        assert client.health()["cookie"] is None


def test_dashboard_uses_one_fresh_scope_per_render(monkeypatch):
    from app import runtime
    from streamlit.runtime.pages_manager import PagesManager

    # AppTest shares this discovery flag process-wide; restore it after testing
    # a real file with a pages/ directory so from_string tests remain isolated.
    monkeypatch.setattr(PagesManager, "uses_pages_directory", None)

    def handle(request):
        if request.url.path == "/departments":
            return httpx.Response(200, json=[])
        if request.url.path == "/data/status":
            return httpx.Response(200, json={"status": "NO_DATA_READY", "quality": {}})
        return httpx.Response(200, json={"rows": [], "horizons": []})

    client, sessions = client_with_sessions(monkeypatch, handle)
    monkeypatch.setattr(runtime, "get_api_client", lambda: client)
    app = AppTest.from_file("app/dashboard.py").run()
    assert not app.exception and len(sessions) == 1 and sessions[0].is_closed
    app.run()
    assert not app.exception and len(sessions) == 2 and sessions[1].is_closed
