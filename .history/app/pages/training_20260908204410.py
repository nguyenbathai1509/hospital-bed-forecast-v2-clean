from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text


def render(client: HospitalApiClient) -> None:
    page_header(
        "🧠 Huấn luyện",
        "Training chạy bất đồng bộ qua FastAPI. Streamlit chỉ tạo/poll persistent Training Job, không train model trong UI process.",
    )

    try:
        status = client.data_status()
        runs = client.training_runs(limit=30).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    q = status.get("quality", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Data latest", status.get("business_date") or "-")
    c2.metric("Data status", status_text(status.get("status")))
    c3.metric("DQ ERROR", q.get("ERROR", 0))
    c4.metric("DQ CHECK", q.get("CHECK", 0))

    st.write("Model Scope: **GLOBAL**")
    st.write("Candidates: **RF, XGBoost, SVR, LSTM** | Horizons: **H+1, H+3** | Primary metric: **MAE**")

    with st.container(border=True):
        requested_by = st.text_input("requested_by", value="streamlit", max_chars=100)
        random_seed = st.number_input("random_seed", min_value=0, value=42, step=1)
        if st.button("BẮT ĐẦU TRAIN", type="primary"):
            try:
                job = client.start_training(
                    requested_by=requested_by,
                    random_seed=int(random_seed),
                )
                st.session_state["training_job_id"] = job["job_id"]
                st.session_state["training_job"] = job
                st.success(
                    f"Training Job: {job['job_id']} | status={job['status']} | reused={job['reused']}"
                )
            except ApiClientError as exc:
                show_api_error(exc)

    job_id = st.session_state.get("training_job_id")
    if job_id:
        st.subheader("Training Job hiện tại")
        if st.button("CẬP NHẬT TRẠNG THÁI JOB"):
            try:
                st.session_state["training_job"] = client.training_status(str(job_id))
            except ApiClientError as exc:
                show_api_error(exc)

        job = st.session_state.get("training_job") or {}
        st.json(job)
        if job.get("status") == "COMPLETED" and job.get("training_run_id"):
            st.success(f"Training Run hoàn thành: {job['training_run_id']}")

    st.subheader("Training Run history")
    dataframe(runs, height=340)