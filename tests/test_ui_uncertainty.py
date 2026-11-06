import json

import httpx
from streamlit.testing.v1 import AppTest

from app.api_client import HospitalApiClient


ROW = {"candidate_id": "TEST", "department_id": 343, "horizon": 1,
       "origin_date": "2026-08-31", "target_date": "2026-09-01", "prediction_raw": 50,
       "issued_at": "2026-08-31T09:00:00"}


def test_client_sends_only_prediction_context_and_original_issue_time():
    def handle(request):
        assert request.method == "POST" and request.url.path == "/forecasts/uncertainty"
        assert json.loads(request.content) == {key: ROW[key] for key in
            ("candidate_id", "department_id", "horizon", "origin_date", "prediction_raw")} | {
                "forecast_created_at": ROW["issued_at"]}
        return httpx.Response(200, json={"status": "INSUFFICIENT_DATA"})
    client = HospitalApiClient("http://test", transport=httpx.MockTransport(handle))
    assert client.forecast_uncertainty(ROW)["status"] == "INSUFFICIENT_DATA"


def app_with_status(status):
    app = AppTest.from_string('''
import streamlit as st
from app.uncertainty_view import render_uncertainty
class Client:
    def forecast_uncertainty(self, row):
        st.session_state["calls"] += 1
        return {"status": st.session_state["status"], "lower_beds": 40, "upper_beds": 60,
                "sample_count": 30 if st.session_state["status"] == "AVAILABLE" else 2,
                "minimum_samples": 30, "calibration_start": "2026-08-01",
                "calibration_end": "2026-08-30", "reason": st.session_state["reason"]}
render_uncertainty(st.session_state["rows"], Client(), scope="test")
''')
    app.session_state["status"] = status
    app.session_state["reason"] = "Khoảng tham khảo, không bảo đảm 90%."
    app.session_state["rows"] = [dict(ROW)]
    app.session_state["calls"] = 0
    return app.run()


def test_interval_requires_explicit_click_and_never_confirms_forecasts():
    app = app_with_status("AVAILABLE")
    assert not app.exception and app.session_state["calls"] == 0
    assert len(app.button) == 1
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "40–60 giường"
    assert app.session_state["calls"] == 1
    app.session_state["rows"] = [dict(ROW, prediction_raw=70)]
    app.run()
    assert not app.metric  # A different point must not reuse the old band.


def test_insufficient_history_shows_no_numeric_band():
    app = app_with_status("INSUFFICIENT_DATA")
    app.button[0].click().run()
    assert not app.exception
    assert not app.metric
    assert "2/30" in app.info[0].value
