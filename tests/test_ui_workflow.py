"""Interactive presentation tests. All operations use an in-memory fake, never SQL/HTTP."""
from copy import deepcopy
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.api_client import ApiClientError, ApiErrorPayload, HospitalApiClient


DAY = "2026-06-30"
ROW = {
    "draft_id": "DRAFT_TEST", "candidate_id": "CAND_1", "department_id": 343,
    "horizon": 1, "origin_date": DAY, "target_date": "2026-07-01",
    "model_family": "RF", "prediction_raw": 42.2, "prediction_rounded": 42,
    "predicted_utilization_pct": 84.0,
}


class WorkflowClient:
    def __init__(self):
        self.calls = []
        self.fail = set()
        self.ready = True
        self.day = DAY
        self.depts = [{"department_id": 343, "department_name": "Khoa A"},
                      {"department_id": 344, "department_name": "Khoa B"}]
        self.candidates = [
            {"candidate_id": f"CAND_{h}", "run_id": "RUN_TEST", "horizon": h,
             "model_family": "RF", "registry_status": "CANDIDATE", "mae": 1.0}
            for h in (1, 3)
        ]
        self.production = {"business_date": DAY, "horizons": [
            {"horizon": h, "active": {"candidate_id": f"CAND_{h}", "model_family": "RF"},
             "normal_change_quota_used": False,
             "recommendation": {"recommended_candidate_id": f"CAND_{h}",
                                "recommended_family": "RF", "action": "KEEP"}}
            for h in (1, 3)
        ]}
        self.drafts = []
        self.officials = []
        self.job_status = "PENDING"
        self.started = False
        self.pipeline_result = "DATA_READY"
        self.monitoring_status = "WAITING_FOR_ACTUAL"
        self.pipeline_history = []

    def record(self, name, kwargs=None):
        self.calls.append((name, deepcopy(kwargs or {})))
        if name in self.fail:
            raise ApiClientError(ApiErrorPayload(None, "API_TIMEOUT", "Chưa xác minh được kết quả; kiểm tra trạng thái trước khi gửi lại."))

    def data_status(self):
        self.record("data_status")
        return {"status": "DATA_READY" if self.ready else "NO_DATA_READY",
                "business_date": self.day if self.ready else None,
                "pipeline_run_id": f"PIPE_{self.day}" if self.ready else None, "quality": {}}

    def departments(self):
        self.record("departments")
        return deepcopy(self.depts)

    def pipeline_runs(self, **kwargs):
        self.record("pipeline_runs", kwargs)
        return {"rows": deepcopy(self.pipeline_history)}

    def run_pipeline(self):
        self.record("run_pipeline")
        self.ready = self.pipeline_result == "DATA_READY"
        self.day = "2026-07-01"
        result = {"run_id": "PIPE_NEW", "status": self.pipeline_result, "business_date": self.day}
        self.pipeline_history.insert(0, result)
        return deepcopy(result)

    def data_quality(self, **kwargs):
        self.record("data_quality", kwargs)
        return {"rows": []}

    def history(self, **kwargs):
        self.record("history", kwargs)
        return {"rows": []}

    def training_runs(self, **kwargs):
        self.record("training_runs", kwargs)
        rows = [{"run_id": "RUN_TEST", "business_date": self.day, "status": self.job_status}] if self.started else []
        return {"rows": [r for r in rows if not kwargs.get("status") or r["status"] == kwargs["status"]]}

    def start_training(self, **kwargs):
        self.record("start_training", kwargs)
        self.started = True
        return {"job_id": "JOB_TEST", "status": self.job_status, "reused": False}

    def training_status(self, job_id):
        self.record("training_status", {"job_id": job_id})
        return {"job_id": job_id, "status": self.job_status,
                "training_run_id": "RUN_TEST" if self.job_status == "COMPLETED" else None}

    def training_results(self, run_id):
        self.record("training_results", {"run_id": run_id})
        return {"run": {}, "candidates": deepcopy(self.candidates)}

    def training_evaluation(self, **kwargs):
        self.record("training_evaluation", kwargs)
        return {"rows": [], "split": {"train_start": "2026-01-01", "train_end": "2026-04-30",
                "validation_start": "2026-05-01", "validation_end": "2026-05-31",
                "test_start": "2026-06-01", "test_end": DAY}}

    def models(self, **kwargs):
        self.record("models", kwargs)
        return {"rows": deepcopy(self.candidates)}

    def production_models(self):
        self.record("production_models")
        return deepcopy(self.production)

    def official_forecasts(self, **kwargs):
        self.record("official_forecasts", kwargs)
        return {"rows": [deepcopy(row) for row in self.officials if all(
            kwargs.get(key) in (None, row[key]) for key in ("origin_date", "department_id", "horizon"))]}

    def production_predict(self, **kwargs):
        self.record("production_predict", kwargs)
        row = dict(ROW, origin_date=kwargs["origin_date"], department_id=kwargs["department_ids"][0],
                   horizon=kwargs["horizons"][0])
        self.drafts = [row]
        return {"status": "DRAFT_READY", "origin_date": kwargs["origin_date"], "created": [deepcopy(row)], "reused": []}

    def confirm_official(self, **kwargs):
        name = "confirm_commit" if kwargs.get("confirmation") else "confirm_plan"
        self.record(name, kwargs)
        drafts = [row for row in self.drafts if row["origin_date"] == kwargs["origin_date"]]
        if kwargs.get("confirmation"):
            self.officials.extend(deepcopy(drafts))
            self.drafts = [r for r in self.drafts if r not in drafts]
            return {"status": "COMPLETED", "origin_date": kwargs["origin_date"]}
        return {"status": "CONFIRMATION_REQUIRED" if drafts else "NO_DRAFTS",
                "origin_date": kwargs["origin_date"], "draft_count": len(drafts), "drafts": deepcopy(drafts)}

    def forecast_preview(self, **kwargs):
        self.record("forecast_preview", kwargs)
        row = dict(ROW, department_id=kwargs["department_ids"][0], horizon=kwargs["horizons"][0],
                   origin_date=kwargs["origin_date"])
        return {"predictions": [row], "persisted": False, "official": False, "monitoring_eligible": False}

    def promote_models(self, **kwargs):
        self.record("promote_commit" if kwargs.get("confirmation") else "promote_plan", kwargs)
        if kwargs.get("confirmation"):
            for state in self.production["horizons"]:
                if state["horizon"] in kwargs["horizons"]:
                    state["normal_change_quota_used"] = True
        return {"status": "COMPLETED" if kwargs.get("confirmation") else "CONFIRMATION_REQUIRED"}

    def rollback_model(self, **kwargs):
        self.record("rollback_commit" if kwargs.get("confirmation") else "rollback_plan", kwargs)
        return {"status": "COMPLETED" if kwargs.get("confirmation") else "CONFIRMATION_REQUIRED"}

    def monitoring(self):
        self.record("monitoring")
        return {"run": {"status": self.monitoring_status}, "metrics": []}

    def run_monitoring(self, pipeline_run_id):
        self.record("run_monitoring", {"pipeline_run_id": pipeline_run_id})
        return {"status": self.monitoring_status}


@pytest.fixture(autouse=True)
def block_real_api(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Workflow tests must never call the real API")
    monkeypatch.setattr(HospitalApiClient, "_request", forbidden)


def render_page(page, client=None, *, isolate_reruns=True):
    client = client or WorkflowClient()
    app = AppTest.from_string('''
import importlib
from contextlib import nullcontext
from unittest.mock import patch
import streamlit as st
page = importlib.import_module("app.pages." + st.session_state["test_page"])
# AppTest 1.49 merges deltas from an immediate rerun, retaining widgets
# removed by the final run. Model the same rerun as a separate AppTest.run
# so assertions see only the final frame, like the browser does.
def request_rerun():
    st.session_state["test_rerun_requested"] = True
    st.stop()
rerun_context = patch("streamlit.rerun", request_rerun) if st.session_state["test_isolate_reruns"] else nullcontext()
with rerun_context:
    page.render(st.session_state["test_client"])
''', default_timeout=15)
    app.session_state["test_client"] = client
    app.session_state["test_page"] = page
    app.session_state["test_rerun_requested"] = False
    app.session_state["test_isolate_reruns"] = isolate_reruns
    app.run()
    assert not app.exception
    return app, client


def control(elements, label):
    return next(element for element in elements if element.label == label)


def click(app, label):
    button = control(app.button, label)
    assert not button.disabled
    button.click().run()
    assert not app.exception
    if app.session_state["test_rerun_requested"]:
        app.session_state["test_rerun_requested"] = False
        app.run()
        assert not app.exception


def calls(client, name):
    return [kwargs for method, kwargs in client.calls if method == name]


@pytest.mark.parametrize("page,method", [
    ("data", "data_status"), ("training", "data_status"), ("training_results", "training_runs"),
    ("models", "production_models"), ("forecast", "data_status"), ("monitoring", "monitoring"),
])
def test_disconnected_pages_show_error_without_crashing_or_mutating(page, method):
    client = WorkflowClient()
    client.fail.add(method)
    app, client = render_page(page, client)
    assert app.error and "API_TIMEOUT" in app.error[0].value
    assert all(name not in {"run_pipeline", "start_training", "production_predict", "confirm_commit",
                           "promote_commit", "rollback_commit", "run_monitoring"} for name, _ in client.calls)


@pytest.mark.parametrize("status,level", [("DATA_READY", "success"), ("WAITING", "warning"), ("FAILED", "error")])
def test_pipeline_feedback_matches_status_and_refreshes_history(status, level):
    app, client = render_page("data")
    client.pipeline_result = status
    assert control(app.button, "CHẠY XỬ LÝ DỮ LIỆU").disabled
    app.checkbox(key="pipeline_ack").check().run()
    click(app, "CHẠY XỬ LÝ DỮ LIỆU")
    assert any("Xử lý dữ liệu kết thúc" in e.value for e in getattr(app, level))
    assert len(calls(client, "run_pipeline")) == 1
    assert control(app.button, "CHẠY XỬ LÝ DỮ LIỆU").disabled
    assert any("PIPE_NEW" in str(table.value) for table in app.dataframe)


def test_invalid_history_range_never_calls_api():
    app, client = render_page("data")
    client.calls.clear()
    control(app.date_input, "Từ ngày").set_value(date(2026, 7, 2)).run()
    assert not app.exception and app.warning
    assert not calls(client, "history")


def test_training_without_ready_data_is_disabled():
    client = WorkflowClient()
    client.ready = False
    app, client = render_page("training", client)
    assert control(app.button, "BẮT ĐẦU HUẤN LUYỆN").disabled
    assert app.warning and not calls(client, "start_training")


def test_training_progress_failure_and_refresh_do_not_resubmit():
    app, client = render_page("training")
    click(app, "BẮT ĐẦU HUẤN LUYỆN")
    assert any("Đang chờ" in msg.value for msg in app.info)
    client.job_status = "RUNNING"
    click(app, "CẬP NHẬT TRẠNG THÁI")
    assert any("Đang chạy" in msg.value for msg in app.info)
    client.fail.add("training_status")
    click(app, "CẬP NHẬT TRẠNG THÁI")
    assert app.error and app.warning
    assert not any("Đang chạy" in msg.value for msg in app.info)
    client.fail.clear()
    client.job_status = "FAILED"
    click(app, "CẬP NHẬT TRẠNG THÁI")
    assert any("thất bại" in msg.value for msg in app.error)
    assert len(calls(client, "start_training")) == 1


def test_evaluation_without_departments_keeps_summary_without_key_error():
    client = WorkflowClient()
    client.started, client.job_status, client.depts = True, "COMPLETED", []
    app, client = render_page("training_results", client)
    assert any("Chưa có khoa hoạt động" in msg.value for msg in app.info)
    assert not calls(client, "training_evaluation")


@pytest.mark.parametrize("change", ["department", "horizon", "date", "mode", "candidate", "data_version", "recommendation"])
def test_preview_is_cleared_when_its_context_changes(change):
    app, client = render_page("forecast")
    if change == "candidate":
        client.candidates.append(dict(client.candidates[0], candidate_id="OTHER", model_family="SVR"))
        control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("CUSTOM").run()
    click(app, "XEM THỬ DỰ BÁO")
    assert any(metric.value == "42 giường" for metric in app.metric)
    if change == "department":
        app.selectbox(key="forecast_department").select_index(1).run()
    elif change == "horizon":
        control(app.selectbox, "Mốc dự báo").set_value(3).run()
    elif change == "date":
        control(app.date_input, "Ngày dữ liệu").set_value(date(2026, 6, 29)).run()
    elif change == "mode":
        control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("PRODUCTION").run()
    elif change == "candidate":
        control(app.selectbox, "Mô hình dùng để xem thử").select_index(1).run()
    elif change == "data_version":
        client.day = "2026-07-01"
        app.run()
    else:
        client.production["horizons"][0]["recommendation"]["recommended_candidate_id"] = "NEW"
        app.run()
    assert not app.exception
    assert not any(metric.value == "42 giường" for metric in app.metric)
    assert len(calls(client, "forecast_preview")) == 1


def test_failed_preview_does_not_show_the_previous_success():
    app, client = render_page("forecast")
    click(app, "XEM THỬ DỰ BÁO")
    client.fail.add("forecast_preview")
    click(app, "XEM THỬ DỰ BÁO")
    assert app.error and not app.metric


def test_missing_data_or_models_blocks_impossible_forecast_actions():
    client = WorkflowClient()
    client.ready = False
    app, _ = render_page("forecast", client)
    assert app.warning and not app.button
    client.ready = True
    client.candidates = []
    client.production["horizons"] = []
    app, _ = render_page("forecast", client)
    assert control(app.button, "TẠO BẢN NHÁP DỰ BÁO").disabled
    control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("CUSTOM").run()
    assert control(app.button, "XEM THỬ DỰ BÁO").disabled


def test_draft_card_does_not_follow_user_to_another_department():
    app, client = render_page("forecast")
    click(app, "TẠO BẢN NHÁP DỰ BÁO")
    assert any(metric.value == "42 giường" for metric in app.metric)
    app.selectbox(key="forecast_department").select_index(1).run()
    assert not app.exception and not app.metric
    assert len(calls(client, "production_predict")) == 1


@pytest.mark.parametrize("change", ["date", "drafts", "unreachable"])
def test_official_consent_is_reset_if_plan_changes_or_cannot_be_read(change):
    client = WorkflowClient()
    client.drafts = [dict(ROW)]
    app, client = render_page("forecast", client)
    app.text_input(key="official_confirmation").set_value("I_CONFIRM_OFFICIAL").run()
    assert not control(app.button, "XÁC NHẬN DỰ BÁO CHÍNH THỨC").disabled
    if change == "date":
        control(app.date_input, "Ngày dữ liệu").set_value(date(2026, 6, 29)).run()
    elif change == "drafts":
        client.drafts.append(dict(ROW, draft_id="SECOND", department_id=344))
        app.run()
    else:
        client.fail.add("confirm_plan")
        app.run()
    assert not app.exception
    assert control(app.button, "XÁC NHẬN DỰ BÁO CHÍNH THỨC").disabled
    assert app.text_input(key="official_confirmation").value == ""
    assert not calls(client, "confirm_commit")


@pytest.mark.parametrize("change", ["horizon", "reason", "production", "preview_failure"])
def test_rollback_requires_a_plan_matching_current_selection(change):
    app, client = render_page("models")
    click(app, "KIỂM TRA KẾ HOẠCH KHÔI PHỤC")
    app.text_input(key="rollback_confirmation").set_value("I_CONFIRM_EMERGENCY_ROLLBACK").run()
    if change == "horizon":
        control(app.selectbox, "Mốc dự báo cần khôi phục").set_value(3).run()
    elif change == "reason":
        control(app.text_input, "Lý do khôi phục (lưu vết)").set_value("Lý do mới").run()
    elif change == "production":
        client.production["business_date"] = "2026-07-01"
        app.run()
    else:
        client.fail.add("rollback_plan")
        click(app, "KIỂM TRA KẾ HOẠCH KHÔI PHỤC")
    assert not app.exception
    assert not any(b.label == "XÁC NHẬN KHÔI PHỤC KHẨN CẤP" for b in app.button)
    assert not calls(client, "rollback_commit")


def test_rollback_success_clears_consent_and_plan():
    app, client = render_page("models")
    click(app, "KIỂM TRA KẾ HOẠCH KHÔI PHỤC")
    app.text_input(key="rollback_confirmation").set_value("I_CONFIRM_EMERGENCY_ROLLBACK").run()
    click(app, "XÁC NHẬN KHÔI PHỤC KHẨN CẤP")
    assert app.success and len(calls(client, "rollback_commit")) == 1
    assert not any(b.label == "XÁC NHẬN KHÔI PHỤC KHẨN CẤP" for b in app.button)


@pytest.mark.parametrize("change", ["reason", "production", "preview_failure"])
def test_promotion_does_not_commit_a_stale_or_failed_plan(change):
    app, client = render_page("models")
    app.checkbox(key="promotion_include_h1").check().run()
    click(app, "XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    app.text_input(key="promotion_confirmation").set_value("I_CONFIRM_PROMOTION").run()
    if change == "reason":
        control(app.text_input, "Lý do thay đổi mô hình").set_value("Lý do mới").run()
    elif change == "production":
        client.production["business_date"] = "2026-07-01"
        app.run()
    else:
        client.fail.add("promote_plan")
        click(app, "XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    assert not app.exception
    assert all(b.disabled for b in app.button if b.label == "XÁC NHẬN ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    assert not calls(client, "promote_commit")


def test_complete_user_journey_uses_only_fake_operations():
    client = WorkflowClient()
    client.ready = False
    app, _ = render_page("data", client)
    app.checkbox(key="pipeline_ack").check().run()
    click(app, "CHẠY XỬ LÝ DỮ LIỆU")
    app.session_state["test_page"] = "training"
    app.run()
    click(app, "BẮT ĐẦU HUẤN LUYỆN")
    client.job_status = "COMPLETED"
    click(app, "CẬP NHẬT TRẠNG THÁI")
    assert any("RUN_TEST" in msg.value for msg in app.success)
    app.session_state["test_page"] = "training_results"
    app.run()
    assert not app.exception and calls(client, "training_evaluation")
    app.session_state["test_page"] = "models"
    app.run()
    app.checkbox(key="promotion_include_h1").check().run()
    click(app, "XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    app.text_input(key="promotion_confirmation").set_value("I_CONFIRM_PROMOTION").run()
    click(app, "XÁC NHẬN ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    app.session_state["test_page"] = "forecast"
    app.run()
    assert control(app.button, "XÁC NHẬN DỰ BÁO CHÍNH THỨC").disabled
    click(app, "TẠO BẢN NHÁP DỰ BÁO")
    app.text_input(key="official_confirmation").set_value("I_CONFIRM_OFFICIAL").run()
    click(app, "XÁC NHẬN DỰ BÁO CHÍNH THỨC")
    assert any("không thể thay đổi" in msg.value for msg in app.success)
    assert not any(b.label == "TẠO BẢN NHÁP DỰ BÁO" for b in app.button)
    app.session_state["test_page"] = "monitoring"
    app.run()
    click(app, "CHẠY GIÁM SÁT")
    assert any("Chờ dữ liệu thực tế" in msg.value for msg in app.info)
    for operation in ("run_pipeline", "start_training", "promote_commit", "production_predict", "confirm_commit", "run_monitoring"):
        assert len(calls(client, operation)) == 1


@pytest.mark.parametrize("change", ["drafts", "unreachable"])
def test_official_plan_change_during_confirm_click_never_commits(change):
    client = WorkflowClient()
    client.drafts = [dict(ROW)]
    app, client = render_page("forecast", client)
    app.text_input(key="official_confirmation").set_value("I_CONFIRM_OFFICIAL").run()
    if change == "drafts":
        client.drafts.append(dict(ROW, draft_id="NEW", department_id=344))
    else:
        client.fail.add("confirm_plan")
    click(app, "XÁC NHẬN DỰ BÁO CHÍNH THỨC")
    assert not calls(client, "confirm_commit")
    assert control(app.button, "XÁC NHẬN DỰ BÁO CHÍNH THỨC").disabled


def test_promotion_state_change_during_confirm_click_never_commits():
    app, client = render_page("models")
    app.checkbox(key="promotion_include_h1").check().run()
    click(app, "XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    app.text_input(key="promotion_confirmation").set_value("I_CONFIRM_PROMOTION").run()
    client.production["horizons"][0]["normal_change_quota_used"] = True
    click(app, "XÁC NHẬN ĐƯA MÔ HÌNH VÀO SỬ DỤNG")
    assert not calls(client, "promote_commit")


def test_missing_date_is_a_warning_instead_of_a_crash():
    app, client = render_page("forecast")
    client.calls.clear()
    control(app.date_input, "Ngày dữ liệu").set_value(None).run()
    assert not app.exception and app.warning
    assert not calls(client, "official_forecasts")


@pytest.mark.parametrize("page,button,operation", [
    ("data", "CHẠY XỬ LÝ DỮ LIỆU", "run_pipeline"),
    ("training", "BẮT ĐẦU HUẤN LUYỆN", "start_training"),
    ("forecast", "TẠO BẢN NHÁP DỰ BÁO", "production_predict"),
    ("monitoring", "CHẠY GIÁM SÁT", "run_monitoring"),
])
def test_failed_actions_show_no_success_and_are_not_replayed_on_refresh(page, button, operation):
    app, client = render_page(page)
    if page == "data":
        app.checkbox(key="pipeline_ack").check().run()
    client.fail.add(operation)
    click(app, button)
    assert app.error and not app.success
    app.run()
    assert not app.exception
    assert len(calls(client, operation)) == 1


def test_native_streamlit_rerun_refreshes_without_replaying_pipeline():
    # Also smoke-test real st.rerun, without the final-frame adapter above.
    app, client = render_page("data", isolate_reruns=False)
    app.checkbox(key="pipeline_ack").check().run()
    click(app, "CHẠY XỬ LÝ DỮ LIỆU")
    assert app.session_state["pipeline_ack"] is False
    assert len(calls(client, "run_pipeline")) == 1
    assert any("PIPE_NEW" in str(table.value) for table in app.dataframe)


def test_native_streamlit_rerun_refreshes_official_after_commit():
    client = WorkflowClient()
    client.drafts = [dict(ROW)]
    app, client = render_page("forecast", client, isolate_reruns=False)
    app.text_input(key="official_confirmation").set_value("I_CONFIRM_OFFICIAL").run()
    click(app, "XÁC NHẬN DỰ BÁO CHÍNH THỨC")
    assert any("không thể thay đổi" in msg.value for msg in app.success)
    assert len(calls(client, "confirm_commit")) == 1
    assert not client.drafts


def test_forecast_only_loads_candidate_list_for_custom_preview():
    app, client = render_page("forecast")
    assert not calls(client, "models")
    control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("PRODUCTION").run()
    assert not calls(client, "models")
    control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("CUSTOM").run()
    assert calls(client, "models") == [{"horizon": 1, "limit": 200}]
    control(app.selectbox, "Mốc dự báo").set_value(3).run()
    assert calls(client, "models")[-1] == {"horizon": 3, "limit": 200}


def test_optional_candidate_api_failure_does_not_hide_official_forecast():
    client = WorkflowClient()
    client.officials = [dict(ROW)]
    client.fail.add("models")
    app, client = render_page("forecast", client)
    assert not app.error and any(m.value == "42 giường" for m in app.metric)
    control(app.selectbox, "Cách chọn mô hình để xem thử").set_value("CUSTOM").run()
    assert not app.exception and app.error
    assert any(m.value == "42 giường" for m in app.metric)
    assert not calls(client, "forecast_preview")


def test_no_completed_training_does_not_load_unused_departments():
    app, client = render_page("training_results")
    assert app.info
    assert not calls(client, "departments")
