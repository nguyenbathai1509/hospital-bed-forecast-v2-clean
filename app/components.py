from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError


STATUS_LABELS = {
    "DATA_READY": "Dữ liệu sẵn sàng",
    "NO_DATA_READY": "Chưa có dữ liệu sẵn sàng",
    "WAITING": "Đang chờ dữ liệu",
    "NO_DRAFTS": "Chưa có bản nháp chờ xác nhận",
    "NO_CHANGE": "Không có thay đổi",
    "COMPLETED": "Hoàn thành",
    "RUNNING": "Đang chạy",
    "PENDING": "Đang chờ",
    "FAILED": "Thất bại",
    "WAITING_FOR_ACTUAL": "Chờ dữ liệu thực tế",
    "PARTIAL": "Đã khớp một phần",
    "NO_OFFICIALS": "Chưa có dự báo chính thức",
    "OFFICIAL": "Chính thức",
    "DRAFT": "Bản nháp",
    "ACTIVE": "Đang sử dụng",
    "SCHEDULED": "Đã lên lịch",
    "ARCHIVED": "Đã lưu trữ",
    "CONFIRMATION_REQUIRED": "Cần xác nhận",
    "RESET_COMPLETED": "Đặt lại hoàn tất",
    "NO_DRAFTS_NEEDED": "Không cần tạo bản nháp",
}


COLUMN_LABELS = {
    "comparison_name": "Mô hình / phương pháp",
    "comparison_kind": "Nhóm",
    "baseline_name": "Mô hình đối chiếu",
    "fold": "Cửa sổ",
    "fit_end": "Học dữ liệu đến ngày",
    "start": "Bắt đầu đánh giá",
    "end": "Kết thúc đánh giá",
    "sample_count": "Số mẫu đánh giá",
    "business_date": "Ngày dữ liệu",
    "origin_date": "Ngày dữ liệu",
    "target_date": "Ngày cần dự báo",
    "run_id": "Mã lần chạy",
    "pipeline_run_id": "Mã lần xử lý dữ liệu",
    "training_run_id": "Mã lần huấn luyện",
    "monitoring_run_id": "Mã lần giám sát",
    "job_id": "Mã yêu cầu huấn luyện",
    "candidate_id": "Mã mô hình",
    "model_candidate_id": "Mã mô hình",
    "model_family": "Mô hình",
    "horizon": "Mốc dự báo",
    "department_id": "Mã khoa",
    "department_name": "Tên khoa",
    "status": "Trạng thái",
    "registry_status": "Trạng thái mô hình",
    "severity": "Độ nghiêm trọng",
    "check_code": "Mã kiểm tra",
    "message": "Nội dung",
    "action": "Hành động",
    "reason": "Lý do",
    "mae": "MAE",
    "rmse": "RMSE",
    "wape": "WAPE",
    "r2": "R²",
    "bias": "Độ lệch",
    "p90_absolute_error": "Sai số tuyệt đối P90",
    "within_2_beds_pct": "Tỷ lệ sai số trong ±2 giường",
    "prediction_raw": "Dự báo thô",
    "prediction_rounded": "Số giường dự báo",
    "predicted_utilization_pct": "Công suất dự báo (%)",
    "actual_occupied_beds": "Số giường thực tế",
    "actual": "Thực tế",
    "predicted": "Dự báo",
    "residual": "Sai số",
    "occupied_beds": "Giường đang sử dụng",
    "planned_beds": "Giường kế hoạch",
    "capacity_alert": "Cảnh báo công suất",
    "capacity_excess_beds": "Số giường vượt kế hoạch",
    "metric_scope": "Phạm vi đánh giá",
    "row_count": "Số dòng",
    "table": "Bảng dữ liệu",
    "department_count": "Số khoa",
    "completed_candidate_count": "Số mô hình hoàn thành",
    "feature_version": "Phiên bản đặc trưng",
    "random_seed": "Giá trị khởi tạo ngẫu nhiên",
    "requested_by": "Người yêu cầu",
    "created_by": "Người tạo",
    "created_at": "Thời gian tạo",
    "completed_at": "Thời gian hoàn thành",
    "latest_actual_date": "Ngày thực tế mới nhất",
    "official_total_count": "Số dự báo chính thức",
    "matched_total_count": "Số đã đối chiếu",
    "waiting_for_actual_count": "Số đang chờ thực tế",
    "missing_actual_count": "Số thiếu dữ liệu thực tế",
    "is_recommended": "Được khuyến nghị",
    "reused": "Tái sử dụng kết quả cũ",
}


ACTION_LABELS = {
    "KEEP": "Giữ mô hình hiện tại",
    "PROMOTE": "Đưa mô hình vào sử dụng",
    "IMMEDIATE": "Áp dụng ngay",
    "NEXT_CYCLE": "Áp dụng từ chu kỳ tiếp theo",
}


SEVERITY_LABELS = {
    "ERROR": "Lỗi nghiêm trọng",
    "WARNING": "Cảnh báo",
    "CHECK": "Cần kiểm tra",
}


def page_header(title: str, description: str) -> None:
    st.markdown(
        (
            '<header class="hb-page-header">'
            f"<h1>{escape(title)}</h1>"
            f"<p>{escape(description)}</p>"
            "</header>"
        ),
        unsafe_allow_html=True,
    )


def show_api_error(exc: ApiClientError) -> None:
    prefix = f"{exc.code}"
    if exc.status_code is not None:
        prefix += f" (HTTP {exc.status_code})"
    st.error(f"{prefix}: {exc.message}")
    if exc.details:
        with st.expander("Chi tiết lỗi"):
            st.json(exc.details)


def dataframe(rows: list[dict[str, Any]], *, height: int = 320) -> None:
    if not rows:
        st.info("Chưa có dữ liệu phù hợp.")
        return

    frame = pd.DataFrame(rows).copy()

    if "horizon" in frame.columns:
        frame["horizon"] = frame["horizon"].map(
            lambda value: (
                f"H+{int(value)}"
                if pd.notna(value)
                else "-"
            )
        )

    for column in ("status", "registry_status"):
        if column in frame.columns:
            frame[column] = frame[column].map(
                lambda value: STATUS_LABELS.get(
                    str(value),
                    value,
                )
                if pd.notna(value)
                else "-"
            )

    if "action" in frame.columns:
        frame["action"] = frame["action"].map(
            lambda value: ACTION_LABELS.get(
                str(value),
                value,
            )
            if pd.notna(value)
            else "-"
        )

    if "severity" in frame.columns:
        frame["severity"] = frame["severity"].map(
            lambda value: SEVERITY_LABELS.get(
                str(value),
                value,
            )
            if pd.notna(value)
            else "-"
        )

    for column in frame.columns:
        if pd.api.types.is_bool_dtype(frame[column]):
            frame[column] = frame[column].map(
                {True: "Có", False: "Không"}
            )

    frame = frame.rename(
        columns={
            name: COLUMN_LABELS.get(name, name)
            for name in frame.columns
        }
    )

    st.dataframe(
        frame,
        width="stretch",
        height=height,
        hide_index=True,
    )


def metric_or_dash(label: str, value: Any, help_text: str | None = None) -> None:
    st.metric(label, "-" if value is None else value, help=help_text)


def technical_details(
    payload: Any,
    *,
    label: str = "Chi tiết kỹ thuật",
) -> None:
    """Hide raw API/system payloads from the normal user flow."""
    if payload is None:
        return

    with st.expander(
        label,
        expanded=False,
    ):
        st.json(payload)


def status_text(status: str | None) -> str:
    if status is None:
        return "-"
    return STATUS_LABELS.get(status, status)


def render_prediction_cards(rows: list[dict[str, Any]], *, key_prefix: str | None = None) -> None:
    if not rows:
        st.info("Không có dự báo để hiển thị.")
        return

    for index, row in enumerate(rows):
        panel_key = None if key_prefix is None else f"hb-panel-{key_prefix}-{index}"
        with st.container(border=True, key=panel_key):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Khoa", row.get("department_id"))
            c2.metric("Mốc dự báo", f"H+{row.get('horizon')}")
            c3.metric("Dự báo", f"{row.get('prediction_rounded')} giường")
            c4.metric("Công suất", f"{row.get('predicted_utilization_pct', 0):.1f}%")
            st.caption(
                f"Mô hình: {row.get('model_family')} | Ngày cần dự báo: {row.get('target_date')} | "
                f"Mã mô hình: {row.get('candidate_id')}"
            )
            if row.get("capacity_alert"):
                st.warning(
                    f"Cảnh báo công suất: vượt {row.get('capacity_excess_beds', 0)} giường kế hoạch."
                )
