from __future__ import annotations

from datetime import date

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, render_prediction_cards, show_api_error
from app.viewmodels import department_label


CONFIRM_OFFICIAL = "I_CONFIRM_OFFICIAL"

FORECAST_STATUS_LABELS = {
    "CONFIRMATION_REQUIRED": "Cần xác nhận",
    "COMPLETED": "Hoàn thành",
    "NO_DRAFTS_NEEDED": "Không cần tạo bản nháp",
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

    try:
        data_status = client.data_status()
        departments = client.departments()
        models = client.models(limit=200).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    if not departments:
        st.info("Chưa có khoa hoạt động.")
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

    official_rows = official.get("rows", [])
    if official_rows:
        st.success("🔒 Dự báo chính thức đã tồn tại và không thể thay đổi.")
        render_prediction_cards(official_rows)
    else:
        st.info("Chưa có dự báo chính thức cho khoa, mốc dự báo và ngày này.")

        if st.button("TẠO BẢN NHÁP DỰ BÁO", type="primary"):
            try:
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
            draft_rows = result.get("created", []) + result.get("reused", [])
            render_prediction_cards(draft_rows)

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

            typed = st.text_input(
                f"Gõ chính xác `{CONFIRM_OFFICIAL}` để xác nhận tất cả bản nháp của ngày dữ liệu này thành dự báo chính thức",
                type="password",
                key="official_confirmation",
            )
            if st.button(
                "XÁC NHẬN DỰ BÁO CHÍNH THỨC",
                disabled=typed != CONFIRM_OFFICIAL,
            ):
                try:
                    confirmed = client.confirm_official(
                        origin_date=origin_text,
                        confirmed_by="streamlit",
                        confirmation=typed,
                    )
                    st.success(f"Xác nhận dự báo chính thức: {_forecast_status_label(confirmed.get('status'))}")
                    st.json(confirmed)
                except ApiClientError as exc:
                    show_api_error(exc)

    st.subheader("XEM THỬ DỰ BÁO")
    st.caption("Xem thử không làm thay đổi mô hình đang sử dụng, không tạo bản nháp, không tạo dự báo chính thức và không được tính vào kết quả giám sát.")

    mode = st.selectbox("Cách chọn mô hình để xem thử", ["RECOMMENDED", "PRODUCTION", "CUSTOM"], format_func=lambda x: {"RECOMMENDED": "Mô hình khuyến nghị", "PRODUCTION": "Mô hình đang sử dụng", "CUSTOM": "Tự chọn mô hình"}.get(x, x))
    custom_candidates: dict[str, str] = {}
    if mode == "CUSTOM":
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

    if st.button("XEM THỬ DỰ BÁO"):
        try:
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
        render_prediction_cards(preview.get("predictions", []))