from __future__ import annotations

import streamlit as st

from app.components import dataframe, technical_details


BASELINE_LABELS = {
    "LAST_VALUE": "Giữ nguyên giá trị ngày gần nhất",
    "SEASONAL_NAIVE_7": "Cùng thứ của tuần trước",
    "MOVING_AVERAGE_7": "Trung bình 7 ngày gần nhất",
}


def render_baselines(evidence: dict) -> None:
    st.subheader("Mô hình học máy có tốt hơn cách dự báo đơn giản?")
    benchmark = evidence.get("baseline_benchmarks")
    if not benchmark:
        st.info("Lần huấn luyện này chưa lưu kết quả mô hình đối chiếu. Không tính lại kết quả lịch sử khi xem.")
        return
    if benchmark.get("status") != "COMPLETED":
        st.warning("Chưa đủ dữ liệu cho mô hình đối chiếu.")
        st.caption(benchmark.get("reason", "Thiếu lịch sử cần thiết."))
        return
    st.caption(
        "So sánh MAE, RMSE trên cùng ngày, khoa và ba cửa sổ backtest; càng nhỏ càng tốt. "
        "Mô hình đối chiếu chỉ dùng tham khảo, không tham gia xếp hạng hay tự thay mô hình Production."
    )
    rows = []
    configurations = evidence.get("configurations", {})
    for row in evidence.get("selection_metrics", []):
        candidate = row["candidate_id"]
        family = configurations.get(candidate, {}).get("model_family", "ML")
        rows.append({"comparison_name": f"{family} · {candidate}", "comparison_kind": "Học máy",
                     **{key: row.get(key) for key in ("mae", "rmse", "bias")}})
    for row in benchmark.get("selection_metrics", []):
        name = row["baseline_name"]
        rows.append({"comparison_name": BASELINE_LABELS.get(name, name), "comparison_kind": "Đối chiếu đơn giản",
                     **{key: row.get(key) for key in ("mae", "rmse", "bias")}})
    dataframe(rows, height=300)
    st.caption("Độ lệch = thực tế − dự báo: dương nghĩa là dự báo thiếu giường.")
    with st.expander("Chi tiết mô hình đối chiếu theo từng cửa sổ"):
        dataframe([{**r, "baseline_name": BASELINE_LABELS.get(r.get("baseline_name"), r.get("baseline_name"))}
                   for r in benchmark.get("fold_metrics", [])], height=260)


def render_comparison(recommendations: list[dict], horizon: int) -> str | None:
    """Display stored evidence; never trigger computation on render."""
    recommendation = next((r for r in recommendations if int(r.get("horizon", 0)) == horizon), {})
    evidence = (recommendation.get("policy") or {}).get("comparison")
    if not isinstance(evidence, dict):
        st.caption("Lần huấn luyện này chưa có báo cáo backtest chung; đang hiển thị kết quả lịch sử.")
        return None
    st.subheader("So sánh mô hình trên cùng cửa sổ thời gian")
    status = evidence.get("status")
    if status == "INSUFFICIENT_DATA":
        st.warning(evidence.get("reason", "Chưa đủ dữ liệu để so sánh."))
        st.caption("Giữ mô hình tham chiếu hiện tại. Bảng xếp hạng test gốc chưa đủ làm căn cứ thay mô hình.")
        return status
    if status != "COMPLETED":
        st.info("Chưa có kết quả so sánh hoàn chỉnh.")
        return status
    folds = evidence.get("folds", [])
    audit = evidence.get("audit", {})
    st.caption(
        "Đánh giá lại cấu hình đã chọn của từng mô hình bằng lịch sử mở rộng trước mỗi cửa sổ. "
        "Các mô hình được chấm trên cùng ngày và cùng khoa. Đây là backtest cấu hình, "
        "không phải sai số của các dự báo chính thức đã phát hành."
    )
    if folds:
        st.write(
            f"**{len(folds)} cửa sổ so sánh:** {folds[0]['start']} → {folds[-1]['end']} · "
            f"**Kiểm chứng riêng:** {audit.get('start', '-')} → {audit.get('end', '-')}"
        )
    st.caption(f"Mô hình tham chiếu: {evidence.get('champion_id', '-')}")
    dataframe(evidence.get("selection_metrics", []), height=220)
    with st.expander("Kết quả từng cửa sổ và kiểm chứng riêng"):
        st.write("**Sai số theo từng cửa sổ so sánh**")
        dataframe(evidence.get("fold_metrics", []), height=300)
        st.write("**Kiểm chứng cuối kỳ — không tham gia xếp hạng hoặc quyết định khuyến nghị**")
        dataframe(evidence.get("audit_metrics", []), height=180)
    render_baselines(evidence)
    technical_details(evidence, label="Bằng chứng và cấu hình của lần backtest")
    return status
