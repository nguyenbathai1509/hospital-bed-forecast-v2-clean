from __future__ import annotations

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text


def render(client: HospitalApiClient) -> None:
    page_header(
        "📈 Monitoring",
        "Official-only Production Monitoring. Preview và Draft không được đưa vào metric Production.",
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
        st.info("Chưa có Production Monitoring Run.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Status", status_text(run.get("status")))
        c2.metric("Official", run.get("official_total_count", 0))
        c3.metric("Matched", run.get("matched_total_count", 0))
        c4.metric("Waiting", run.get("waiting_for_actual_count", 0))
        c5.metric("Missing", run.get("missing_actual_count", 0))
        st.caption(
            f"Monitoring Run: {run.get('monitoring_run_id')} | Pipeline: {run.get('pipeline_run_id')} | "
            f"Latest Actual: {run.get('latest_actual_date')}"
        )

    st.subheader("Production metrics")
    dataframe(metrics, height=320)

    if metrics:
        horizon_metrics = [row for row in metrics if row.get("metric_scope") == "HORIZON"]
        if horizon_metrics:
            chart = pd.DataFrame(horizon_metrics)[["horizon", "mae", "bias"]].set_index("horizon")
            st.bar_chart(chart)

    with st.expander("Chạy/recover Monitoring thủ công", expanded=False):
        st.caption(
            "Daily Pipeline là luồng bình thường. Nút này chỉ dùng manual/recovery và vẫn gọi V2-18 qua FastAPI."
        )
        pipeline_run_id = st.text_input(
            "pipeline_run_id",
            value=data_status.get("pipeline_run_id") or "",
        )
        if st.button("CHẠY MONITORING"):
            try:
                result = client.run_monitoring(pipeline_run_id or None)
                st.success(f"Monitoring: {result.get('status')}")
                st.json(result)
            except ApiClientError as exc:
                show_api_error(exc)

    st.info(
        "Drift/retrain recommendation theo rolling window là phần mở rộng của V2 MASTER. "
        "Backend hiện mới có Official-only monitoring metrics; UI không tự suy diễn drift khi chưa có API policy/read-model tương ứng."
    )