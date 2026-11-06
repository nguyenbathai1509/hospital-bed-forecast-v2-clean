from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import metric_or_dash, page_header, show_api_error, status_text
from app.viewmodels import summarize_dashboard


def render(client: HospitalApiClient) -> None:
    page_header(
        "🏠 Tổng quan",
        "State of the day: dữ liệu, pipeline, training, Production và Official Forecast.",
    )

    try:
        data_status = client.data_status()
        departments = client.departments()
        pipeline_runs = client.pipeline_runs(limit=5).get("rows", [])
        training_runs = client.training_runs(limit=10).get("rows", [])
        production = client.production_models()
        origin_date = data_status.get("business_date")
        officials = client.official_forecasts(
            origin_date=origin_date,
            limit=100,
        ).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    summary = summarize_dashboard(
        data_status=data_status,
        pipeline_runs=pipeline_runs,
        training_runs=training_runs,
        production=production,
        officials=officials,
        departments=departments,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_or_dash("Ngày dữ liệu", summary["business_date"])
    with c2:
        metric_or_dash("Data status", status_text(summary["data_status"]))
    with c3:
        latest_pipeline = summary["latest_pipeline"] or {}
        metric_or_dash("Daily Pipeline", status_text(latest_pipeline.get("status")))
    with c4:
        latest_training = summary["latest_training"] or {}
        metric_or_dash("Training gần nhất", status_text(latest_training.get("status")))

    st.subheader("Production hiện tại")
    p1, p2, p3 = st.columns(3)
    h1 = summary["production_h1"] or {}
    h3 = summary["production_h3"] or {}
    p1.metric("Production H+1", h1.get("model_family", "-"))
    p2.metric("Production H+3", h3.get("model_family", "-"))
    p3.metric(
        "Quota đổi Production hôm nay",
        "Đã dùng" if summary["normal_change_quota_used"] else "Chưa dùng",
    )

    r1, r2 = st.columns(2)
    rec1 = summary["recommendation_h1"] or {}
    rec3 = summary["recommendation_h3"] or {}
    r1.info(
        f"Recommended H+1: {rec1.get('recommended_family', '-')} / "
        f"{rec1.get('action', '-')}"
    )
    r2.info(
        f"Recommended H+3: {rec3.get('recommended_family', '-')} / "
        f"{rec3.get('action', '-')}"
    )

    st.subheader("Official Forecast theo khoa/horizon")
    states = summary["official_states"]
    if not states:
        st.info("Chưa có khoa hoạt động.")
    else:
        for state in states:
            icon = "🔒" if state["status"] == "OFFICIAL" else "⚪"
            value = (
                "Pending"
                if state["prediction_rounded"] is None
                else f"{state['prediction_rounded']} giường"
            )
            st.write(
                f"{icon} {state['department_id']} - {state['department_name']} | "
                f"H+{state['horizon']} | {value}"
            )

    st.divider()
    st.caption(
        "Streamlit chỉ hiển thị và gửi lệnh qua FastAPI. Không có truy cập SQL trực tiếp từ giao diện."
    )