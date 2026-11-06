from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, technical_details, status_text
from app.viewmodels import department_label


def render(client: HospitalApiClient) -> None:
    page_header(
        "📂 Dữ liệu",
        "Theo dõi lịch sử xử lý dữ liệu, chất lượng dữ liệu và lịch sử sử dụng giường đã làm sạch.",
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
    c2.metric("Lỗi nghiêm trọng", q.get("ERROR", 0))
    c3.metric("Cảnh báo", q.get("WARNING", 0))
    c4.metric("Cần kiểm tra", q.get("CHECK", 0))

    with st.expander("Chạy xử lý dữ liệu thủ công", expanded=False):
        st.warning(
            "Đây là thao tác xử lý dữ liệu thật. Hệ thống chỉ chuẩn bị dữ liệu sẵn sàng và không tự tạo dự báo chính thức."
        )
        confirm = st.checkbox("Tôi hiểu đây là thao tác xử lý dữ liệu thật.", key="pipeline_ack")
        if st.button("CHẠY XỬ LÝ DỮ LIỆU", disabled=not confirm, type="primary"):
            try:
                result = client.run_pipeline()
                st.success(f"Xử lý dữ liệu kết thúc với trạng thái: {status_text(result.get('status'))}")
                technical_details(
    result,
    label="Chi tiết kỹ thuật của lần xử lý dữ liệu",
)
            except ApiClientError as exc:
                show_api_error(exc)

    st.subheader("Lịch sử xử lý dữ liệu")
    dataframe(runs, height=300)

    st.subheader("Chất lượng dữ liệu")
    run_options = [row.get("run_id") for row in runs if row.get("run_id")]
    selected_run = st.selectbox(
        "Lần xử lý dữ liệu",
        options=run_options,
        index=0 if run_options else None,
        placeholder="Chưa có lần xử lý dữ liệu",
    )
    severity = st.selectbox("Độ nghiêm trọng", ["ALL", "ERROR", "WARNING", "CHECK"], format_func=lambda x: {"ALL": "Tất cả", "ERROR": "Lỗi nghiêm trọng", "WARNING": "Cảnh báo", "CHECK": "Cần kiểm tra"}.get(x, x))
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
        chart["business_date"] = pd.to_datetime(
            chart["business_date"]
        )
        chart = chart.rename(
            columns={
                "business_date": "Ngày dữ liệu",
                "occupied_beds": "Giường đang sử dụng",
                "planned_beds": "Giường kế hoạch",
            }
        )
        chart = chart.set_index(
            "Ngày dữ liệu"
        )
        st.line_chart(
            chart[
                [
                    "Giường đang sử dụng",
                    "Giường kế hoạch",
                ]
            ]
        )
    dataframe(rows, height=320)