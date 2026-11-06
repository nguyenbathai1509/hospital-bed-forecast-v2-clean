from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error
from app.viewmodels import department_label


def render(client: HospitalApiClient) -> None:
    page_header(
        "📂 Dữ liệu",
        "Pipeline history, Data Quality và CLEAN occupancy history. RAW chỉ được tóm tắt qua pipeline/API, không truy cập DB từ UI.",
    )

    try:
        data_status = client.data_status()
        departments = client.departments()
        runs = client.pipeline_runs(limit=30).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    q = data_status.get("quality", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ngày dữ liệu", data_status.get("business_date") or "-")
    c2.metric("DQ ERROR", q.get("ERROR", 0))
    c3.metric("DQ WARNING", q.get("WARNING", 0))
    c4.metric("DQ CHECK", q.get("CHECK", 0))

    with st.expander("Chạy Daily Pipeline thủ công", expanded=False):
        st.warning(
            "Đây là trigger vận hành thật. Pipeline vẫn dừng ở DATA_READY và không tự tạo Official Forecast."
        )
        confirm = st.checkbox("Tôi hiểu đây là lệnh chạy pipeline thật.", key="pipeline_ack")
        if st.button("CHẠY DAILY PIPELINE", disabled=not confirm, type="primary"):
            try:
                result = client.run_pipeline()
                st.success(f"Pipeline kết thúc với trạng thái: {result.get('status')}")
                st.json(result)
            except ApiClientError as exc:
                show_api_error(exc)

    st.subheader("Pipeline history")
    dataframe(runs, height=300)

    st.subheader("Data Quality")
    run_options = [row.get("run_id") for row in runs if row.get("run_id")]
    selected_run = st.selectbox(
        "Pipeline Run",
        options=run_options,
        index=0 if run_options else None,
        placeholder="Chưa có pipeline run",
    )
    severity = st.selectbox("Severity", ["ALL", "ERROR", "WARNING", "CHECK"])
    try:
        dq = client.data_quality(
            pipeline_run_id=selected_run,
            severity=None if severity == "ALL" else severity,
            limit=200,
        )
        dataframe(dq.get("rows", []), height=300)
    except ApiClientError as exc:
        show_api_error(exc)

    st.subheader("CLEAN occupancy history")
    if not departments:
        st.info("Chưa có khoa hoạt động.")
        return

    labels = {department_label(row): row for row in departments}
    selected_label = st.selectbox("Khoa", options=list(labels))
    selected = labels[selected_label]

    default_end = data_status.get("business_date")
    default_end_date = date.fromisoformat(default_end) if default_end else date.today()
    c_start, c_end = st.columns(2)
    with c_start:
        start = st.date_input("Từ ngày", value=None)
    with c_end:
        end = st.date_input("Đến ngày", value=default_end_date)

    try:
        history = client.history(
            department_id=int(selected["department_id"]),
            start_date=None if start is None else start.isoformat(),
            end_date=end.isoformat(),
            limit=500,
        )
    except ApiClientError as exc:
        show_api_error(exc)
        return

    rows = history.get("rows", [])
    if rows:
        chart = pd.DataFrame(rows)
        chart["business_date"] = pd.to_datetime(chart["business_date"])
        chart = chart.set_index("business_date")
        st.line_chart(chart[["occupied_beds", "planned_beds"]])
    dataframe(rows, height=320)