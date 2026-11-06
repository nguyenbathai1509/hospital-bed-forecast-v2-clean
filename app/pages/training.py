from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text, technical_details


def render(client: HospitalApiClient) -> None:
    page_header(
        "🧠 Huấn luyện mô hình",
        "Việc huấn luyện được hệ thống thực hiện ở phía sau. Giao diện chỉ gửi yêu cầu và theo dõi trạng thái huấn luyện.",
    )

    try:
        status = client.data_status()
        runs = client.training_runs(limit=30).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    q = status.get("quality", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ngày dữ liệu mới nhất", status.get("business_date") or "-")
    c2.metric("Trạng thái dữ liệu", status_text(status.get("status")))
    c3.metric("Lỗi nghiêm trọng", q.get("ERROR", 0))
    c4.metric("Cần kiểm tra", q.get("CHECK", 0))

    st.write("Phạm vi mô hình: **Toàn hệ thống**")
    st.write("Các mô hình: **RF, XGBoost, SVR, LSTM** | Mốc dự báo: **H+1, H+3** | Chỉ số đánh giá chính: **MAE**")

    ready = status.get("status") == "DATA_READY"
    if not ready:
        st.warning("Chưa có dữ liệu sẵn sàng để huấn luyện. Hãy sang trang Dữ liệu, xử lý dữ liệu và kiểm tra chất lượng trước.")
    if st.session_state.pop("training_request_accepted", False):
        st.success("Hệ thống đã tiếp nhận yêu cầu. Theo dõi trạng thái bên dưới; huấn luyện tiếp tục chạy ở phía máy chủ.")

    with st.container(border=True, key="hb-panel-training-controls"):
        requested_by = st.text_input("requested_by", value="streamlit", max_chars=100)
        random_seed = st.number_input("random_seed", min_value=0, value=42, step=1)
        can_start = ready and bool(requested_by.strip())
        if st.button("BẮT ĐẦU HUẤN LUYỆN", type="primary", disabled=not can_start) and can_start:
            try:
                with st.spinner("Đang gửi yêu cầu huấn luyện…"):
                    job = client.start_training(
                        requested_by=requested_by.strip(),
                        random_seed=int(random_seed),
                    )
                st.session_state["training_job_id"] = job["job_id"]
                st.session_state["training_job"] = job
                st.session_state["training_request_accepted"] = True
                st.rerun()
            except ApiClientError as exc:
                show_api_error(exc)

    st.caption(
        "Nếu tiến trình huấn luyện bị ngắt, nhấn BẮT ĐẦU HUẤN LUYỆN để kiểm tra và thử lại. "
        "Hệ thống chỉ phục hồi tác vụ mất tín hiệu quá 120 giây; tác vụ còn hoạt động được tái sử dụng."
    )

    job_id = st.session_state.get("training_job_id")
    if job_id:
        st.subheader("Yêu cầu huấn luyện hiện tại")
        st.button("CẬP NHẬT TRẠNG THÁI")
        try:
            with st.spinner("Đang cập nhật trạng thái huấn luyện…"):
                st.session_state["training_job"] = client.training_status(str(job_id))
        except ApiClientError as exc:
            # Do not present a cached job status as if it were just verified.
            st.session_state.pop("training_job", None)
            show_api_error(exc)
            st.warning("Chưa xác minh được trạng thái hiện tại. Hãy cập nhật lại trước khi gửi yêu cầu mới.")

        job = st.session_state.get("training_job") or {}
        technical_details(
            job,
            label="Chi tiết kỹ thuật của yêu cầu huấn luyện",
        )
        if job.get("status") == "COMPLETED" and job.get("training_run_id"):
            st.success(f"Lần huấn luyện đã hoàn thành: {job['training_run_id']}")
            st.info("Chuyển sang Kết quả huấn luyện để xem đánh giá, sau đó chọn mô hình ở trang Quản lý mô hình. Huấn luyện không tự xác nhận dự báo chính thức.")
        elif job.get("status") == "FAILED":
            st.error("Yêu cầu huấn luyện đã thất bại. Xem chi tiết lỗi và nhật ký trước khi thử lại.")
        elif job.get("status") in {"PENDING", "RUNNING"}:
            st.info(f"Yêu cầu {job_id}: {status_text(job.get('status'))}. Nhấn CẬP NHẬT TRẠNG THÁI để theo dõi; không cần gửi lại yêu cầu.")

    st.subheader("Lịch sử huấn luyện")
    dataframe(runs, height=340)
