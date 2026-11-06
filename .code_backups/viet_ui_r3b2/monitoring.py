from __future__ import annotations

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text


def render(client: HospitalApiClient) -> None:
    page_header(
        "📈 Giám sát",
        "Theo dõi độ chính xác của các dự báo chính thức sau khi có dữ liệu thực tế. Kết quả xem thử và bản nháp không được tính vào giám sát.",
    )

    try:
        snapshot = client.monitoring()
        data_status = client.data_status()
    except ApiClientError as exc:
        show_api_error(exc)
        return

    run = snapshot.get("run")
    metrics = snapshot.get("metrics", [])

    if run is None:
        st.info("Chưa có lần giám sát nào.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Trạng thái", status_text(run.get("status")))
        c2.metric("Dự báo chính thức", run.get("official_total_count", 0))
        c3.metric("Đã đối chiếu", run.get("matched_total_count", 0))
        c4.metric("Đang chờ thực tế", run.get("waiting_for_actual_count", 0))
        c5.metric("Thiếu dữ liệu thực tế", run.get("missing_actual_count", 0))
        st.caption(
            f"Lần giám sát: {run.get('monitoring_run_id')} | Lần xử lý dữ liệu: {run.get('pipeline_run_id')} | "
            f"Ngày thực tế mới nhất: {run.get('latest_actual_date')}"
        )

    st.subheader("Chỉ số giám sát dự báo")
    dataframe(metrics, height=320)

    if metrics:
        horizon_metrics = [row for row in metrics if row.get("metric_scope") == "HORIZON"]
        if horizon_metrics:
            chart = pd.DataFrame(horizon_metrics)[["horizon", "mae", "bias"]].rename(columns={"horizon": "Mốc dự báo", "mae": "MAE", "bias": "Độ lệch"}).set_index("Mốc dự báo")
            st.bar_chart(chart)

    with st.expander("Chạy lại giám sát thủ công", expanded=False):
        st.caption(
            "Thông thường hệ thống tự chạy giám sát sau khi xử lý dữ liệu. Nút này chỉ dùng khi cần chạy lại hoặc khôi phục thao tác giám sát."
        )
        pipeline_run_id = st.text_input(
            "Mã lần xử lý dữ liệu",
            value=data_status.get("pipeline_run_id") or "",
        )
        if st.button("CHẠY GIÁM SÁT"):
            try:
                result = client.run_monitoring(pipeline_run_id or None)
                st.success(f"Giám sát: {status_text(result.get('status'))}")
                st.json(result)
            except ApiClientError as exc:
                show_api_error(exc)

    st.info(
        "Chức năng tự động phát hiện mô hình suy giảm theo thời gian và đề xuất huấn luyện lại là phần mở rộng. "
        "Phiên bản hiện tại chỉ tính các chỉ số giám sát từ dự báo chính thức và dữ liệu thực tế; hệ thống chưa tự kết luận mô hình bị suy giảm."
    )