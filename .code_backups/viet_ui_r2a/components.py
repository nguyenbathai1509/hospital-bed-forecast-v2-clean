from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.api_client import ApiClientError


STATUS_LABELS = {
    "DATA_READY": "Dữ liệu sẵn sàng",
    "COMPLETED": "Hoàn thành",
    "RUNNING": "Đang chạy",
    "PENDING": "Đang chờ",
    "FAILED": "Thất bại",
    "WAITING_FOR_ACTUAL": "Chờ Actual",
    "PARTIAL": "Đã khớp một phần",
    "NO_OFFICIALS": "Chưa có Official",
}


def page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


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
    st.dataframe(pd.DataFrame(rows), width="stretch", height=height)


def metric_or_dash(label: str, value: Any, help_text: str | None = None) -> None:
    st.metric(label, "-" if value is None else value, help=help_text)


def status_text(status: str | None) -> str:
    if status is None:
        return "-"
    return STATUS_LABELS.get(status, status)


def render_prediction_cards(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Không có dự báo để hiển thị.")
        return

    for row in rows:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Khoa", row.get("department_id"))
            c2.metric("Horizon", f"H+{row.get('horizon')}")
            c3.metric("Dự báo", f"{row.get('prediction_rounded')} giường")
            c4.metric("Công suất", f"{row.get('predicted_utilization_pct', 0):.1f}%")
            st.caption(
                f"Model: {row.get('model_family')} | Target: {row.get('target_date')} | "
                f"Candidate: {row.get('candidate_id')}"
            )
            if row.get("capacity_alert"):
                st.warning(
                    f"Cảnh báo công suất: vượt {row.get('capacity_excess_beds', 0)} giường kế hoạch."
                )