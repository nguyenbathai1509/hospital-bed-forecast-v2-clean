from __future__ import annotations

from datetime import date

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, render_prediction_cards, show_api_error, technical_details
from app.viewmodels import department_label
from app.uncertainty_view import render_uncertainty


CONFIRM_OFFICIAL = "I_CONFIRM_OFFICIAL"

FORECAST_STATUS_LABELS = {
    "CONFIRMATION_REQUIRED": "Cần xác nhận",
    "COMPLETED": "Hoàn thành",
    "NO_DRAFTS_NEEDED": "Không cần tạo bản nháp",
    "NO_DRAFTS": "Chưa có bản nháp chờ xác nhận",
}


def _forecast_status_label(value: object) -> str:
    if value is None:
        return "-"
    return FORECAST_STATUS_LABELS.get(str(value), str(value))


def _yes_no(value: object) -> str:
    return "Có" if bool(value) else "Không"



def render(client: HospitalApiClient) -> None:
    page_header(
        "🔮 Dự báo",
        "Tạo dự báo bằng mô hình đang sử dụng, xác nhận dự báo chính thức hoặc xem thử kết quả mà không lưu vào hệ thống.",
    )

    confirmed = st.session_state.pop("official_action_result", None)
    if confirmed is not None:
        st.session_state.pop("official_confirmation", None)
        st.session_state.pop("forecast_draft_result", None)
        if confirmed.get("status") == "COMPLETED":
            st.success("Đã xác nhận dự báo chính thức. Giao diện đang tải lại danh sách từ hệ thống.")
        else:
            st.info(f"Xác nhận dự báo chính thức: {_forecast_status_label(confirmed.get('status'))}")
        technical_details(confirmed, label="Chi tiết kỹ thuật của lần xác nhận dự báo")

    try:
        data_status = client.data_status()
        departments = client.departments()
    except ApiClientError as exc:
        show_api_error(exc)
        return

    if not departments:
        st.info("Chưa có khoa hoạt động.")
        return
    if not data_status.get("business_date"):
        st.warning("Chưa có ngày dữ liệu sẵn sàng. Hãy sang trang Dữ liệu và hoàn tất xử lý dữ liệu trước khi dự báo.")
        return

    labels = {department_label(row): row for row in departments}
    c1, c2, c3 = st.columns(3)
    with c1:
        selected_label = st.selectbox("Khoa", options=list(labels), key="forecast_department")
    with c2:
        horizon = st.selectbox("Mốc dự báo", [1, 3], format_func=lambda x: f"H+{x}")
    with c3:
        latest = data_status.get("business_date")
        origin_default = date.fromisoformat(latest) if latest else date.today()
        origin_date = st.date_input("Ngày dữ liệu", value=origin_default)

    if origin_date is None:
        st.warning("Hãy chọn ngày dữ liệu để xem hoặc tạo dự báo.")
        return

    department = labels[selected_label]
    department_id = int(department["department_id"])
    origin_text = origin_date.isoformat()

    st.subheader("DỰ BÁO CHÍNH THỨC")
    try:
        production = client.production_models()
        prod_state = next(
            (row for row in production.get("horizons", []) if int(row["horizon"]) == horizon),
            {},
        )
        active = prod_state.get("active") or {}
        official = client.official_forecasts(
            origin_date=origin_text,
            department_id=department_id,
            horizon=horizon,
            limit=20,
        )
    except ApiClientError as exc:
        show_api_error(exc)
        return

    st.write(
        f"Mô hình đang sử dụng cho H+{horizon}: **{active.get('model_family', '-')}** | "
        f"Mã mô hình: `{active.get('candidate_id', '-')}`"
    )

    forecast_context = (
        origin_text, department_id, horizon, data_status.get("pipeline_run_id"),
        active.get("candidate_id"), (prod_state.get("daily_lock") or {}).get("model_candidate_id"),
    )
    if st.session_state.get("forecast_context") != forecast_context:
        st.session_state.pop("forecast_draft_result", None)
        st.session_state.pop("forecast_preview_result", None)
        st.session_state["forecast_context"] = forecast_context

    official_rows = official.get("rows", [])
    if official_rows:
        st.success("🔒 Dự báo chính thức đã tồn tại và không thể thay đổi.")
        render_prediction_cards(official_rows, key_prefix="official")
        render_uncertainty(official_rows, client, scope="official")
    else:
        st.info("Chưa có dự báo chính thức cho khoa, mốc dự báo và ngày này.")

        can_draft = bool(active.get("candidate_id") or prod_state.get("daily_lock"))
        if not can_draft:
            st.warning(f"Chưa có mô hình vận hành cho H+{horizon}. Hãy chọn mô hình ở trang Quản lý mô hình trước khi tạo bản nháp.")
        if st.button("TẠO BẢN NHÁP DỰ BÁO", type="primary", disabled=not can_draft) and can_draft:
            st.session_state.pop("forecast_draft_result", None)
            try:
                with st.spinner("Đang tạo hoặc lấy lại bản nháp dự báo…"):
                    result = client.production_predict(
                        origin_date=origin_text,
                        department_ids=[department_id],
                        horizons=[horizon],
                        created_by="streamlit",
                    )
                st.session_state["forecast_draft_result"] = result
                if result.get("status") == "NO_DRAFTS_NEEDED":
                    st.info("Không cần tạo bản nháp mới; dự báo này có thể đã được xác nhận chính thức.")
                else:
                    st.success("Bản nháp dự báo đã sẵn sàng. Bản nháp chưa phải là dự báo chính thức.")
            except ApiClientError as exc:
                show_api_error(exc)

        result = st.session_state.get("forecast_draft_result")
        if isinstance(result, dict) and result.get("origin_date") == origin_text:
            draft_rows = [
                row for row in result.get("created", []) + result.get("reused", [])
                if row.get("department_id") == department_id and row.get("horizon") == horizon
            ]
            render_prediction_cards(draft_rows, key_prefix="draft")
            render_uncertainty(draft_rows, client, scope="draft")

        with st.expander("Xác nhận dự báo chính thức", expanded=False):
            try:
                plan = client.confirm_official(
                    origin_date=origin_text,
                    confirmed_by="streamlit",
                    confirmation=None,
                )
            except ApiClientError as exc:
                show_api_error(exc)
                plan = None

            if plan:
                st.write(f"Trạng thái: **{_forecast_status_label(plan.get('status'))}** | Bản nháp chờ xác nhận: {plan.get('draft_count', 0)}")
                dataframe(plan.get("drafts", []), height=220)

            # Consent belongs to the date AND the exact displayed draft plan.
            # Re-enter it if new drafts arrive or the plan cannot be verified.
            plan_snapshot = {"origin_date": origin_text, "plan": plan}
            if st.session_state.get("official_plan_snapshot") != plan_snapshot:
                st.session_state.pop("official_confirmation", None)
                st.session_state["official_plan_snapshot"] = plan_snapshot
            plan_ready = bool(
                plan and plan.get("status") == "CONFIRMATION_REQUIRED"
                and plan.get("draft_count", 0) and plan.get("drafts")
                and plan.get("origin_date") == origin_text
            )
            st.caption("Xác nhận áp dụng cho tất cả bản nháp của ngày đã chọn, không chỉ khoa và mốc dự báo đang xem.")
            typed = st.text_input(
                f"Gõ chính xác `{CONFIRM_OFFICIAL}` để xác nhận tất cả bản nháp của ngày dữ liệu này thành dự báo chính thức",
                type="password",
                key="official_confirmation",
                disabled=not plan_ready,
            )
            if st.button(
                "XÁC NHẬN DỰ BÁO CHÍNH THỨC",
                disabled=not plan_ready or typed != CONFIRM_OFFICIAL,
            ) and plan_ready and typed == CONFIRM_OFFICIAL:
                try:
                    with st.spinner("Đang xác nhận dự báo chính thức…"):
                        confirmed = client.confirm_official(
                            origin_date=origin_text,
                            confirmed_by="streamlit",
                            confirmation=typed,
                        )
                    st.session_state["official_action_result"] = confirmed
                    st.rerun()
                except ApiClientError as exc:
                    show_api_error(exc)

    st.subheader("XEM THỬ DỰ BÁO")
    st.caption("Xem thử không làm thay đổi mô hình đang sử dụng, không tạo bản nháp, không tạo dự báo chính thức và không được tính vào kết quả giám sát.")

    mode = st.selectbox("Cách chọn mô hình để xem thử", ["RECOMMENDED", "PRODUCTION", "CUSTOM"], format_func=lambda x: {"RECOMMENDED": "Mô hình khuyến nghị", "PRODUCTION": "Mô hình đang sử dụng", "CUSTOM": "Tự chọn mô hình"}.get(x, x))
    custom_candidates: dict[str, str] = {}
    if mode == "CUSTOM":
        try:
            models = client.models(horizon=horizon, limit=200).get("rows", [])
        except ApiClientError as exc:
            # Failure of optional model selection must not hide official forecasts.
            st.session_state.pop("forecast_preview_result", None)
            show_api_error(exc)
            return
        compatible = [row for row in models if int(row.get("horizon", 0)) == horizon]
        options = {
            f"{row['model_family']} | {row['candidate_id']} | MAE={row.get('mae')}": row["candidate_id"]
            for row in compatible
        }
        if not options:
            st.warning("Không có mô hình ứng viên phù hợp cho mốc dự báo này.")
        else:
            chosen = st.selectbox("Mô hình dùng để xem thử", list(options))
            custom_candidates[str(horizon)] = options[chosen]

    preview_context = (
        forecast_context, mode, tuple(sorted(custom_candidates.items())),
        (prod_state.get("recommendation") or {}).get("recommended_candidate_id") if mode == "RECOMMENDED" else None,
    )
    if st.session_state.get("forecast_preview_context") != preview_context:
        st.session_state.pop("forecast_preview_result", None)
        st.session_state["forecast_preview_context"] = preview_context

    can_preview = mode != "CUSTOM" or bool(custom_candidates)
    if st.button("XEM THỬ DỰ BÁO", disabled=not can_preview) and can_preview:
        st.session_state.pop("forecast_preview_result", None)
        try:
            with st.spinner("Đang tính kết quả xem thử; không lưu dự báo…"):
                preview = client.forecast_preview(
                    mode=mode,
                    origin_date=origin_text,
                    department_ids=[department_id],
                    horizons=[horizon],
                    custom_candidates=custom_candidates,
                )
            st.session_state["forecast_preview_result"] = preview
        except ApiClientError as exc:
            show_api_error(exc)

    preview = st.session_state.get("forecast_preview_result")
    if isinstance(preview, dict):
        st.info(
            "Kết quả xem thử | "
            f"Lưu vào hệ thống: {_yes_no(preview.get('persisted'))} | "
            f"Là dự báo chính thức: {_yes_no(preview.get('official'))} | "
            f"Được tính vào giám sát: {_yes_no(preview.get('monitoring_eligible'))}"
        )
        render_prediction_cards(preview.get("predictions", []), key_prefix="preview")
        interval_rows = [{**row, "created_at": preview.get("generated_at")}
                         for row in preview.get("predictions", [])]
        render_uncertainty(interval_rows, client, scope="preview")
