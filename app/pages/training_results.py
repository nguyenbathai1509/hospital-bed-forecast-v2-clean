from __future__ import annotations

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.backtest_view import render_comparison
from app.components import dataframe, page_header, show_api_error
from app.viewmodels import (
    TRAINING_METRICS,
    candidate_rows_for_horizon,
    enrich_department_metrics,
    evaluation_chart_frame,
    metric_comparison_rows,
)


def _timeline_chart(split: dict) -> alt.Chart:
    rows = [
        {
            "phase": "Huấn luyện",
            "start": pd.to_datetime(split.get("train_start")),
            "end": pd.to_datetime(split.get("train_end")) + timedelta(days=1),
        },
        {
            "phase": "Xác thực",
            "start": pd.to_datetime(split.get("validation_start")),
            "end": pd.to_datetime(split.get("validation_end")) + timedelta(days=1),
        },
        {
            "phase": "Kiểm tra",
            "start": pd.to_datetime(split.get("test_start")),
            "end": pd.to_datetime(split.get("test_end")) + timedelta(days=1),
        },
    ]
    frame = pd.DataFrame(rows).dropna()
    return (
        alt.Chart(frame)
        .mark_bar(size=28)
        .encode(
            x=alt.X("start:T", title="Thời gian"),
            x2="end:T",
            y=alt.Y(
                "phase:N",
                title=None,
                sort=["Huấn luyện", "Xác thực", "Kiểm tra"],
            ),
            tooltip=[
                alt.Tooltip("phase:N", title="Giai đoạn"),
                alt.Tooltip("start:T", title="Bắt đầu"),
                alt.Tooltip("end:T", title="Kết thúc hiển thị"),
            ],
        )
        .properties(height=150)
    )


def _metric_help(meta: dict) -> str:
    better = meta.get("better")
    if better == "lower":
        return "Càng thấp càng tốt."
    if better == "higher":
        return "Càng cao càng tốt."
    return "Bias càng gần 0 càng tốt."


def render(client: HospitalApiClient) -> None:
    page_header(
        "📊 Kết quả huấn luyện",
        "Các biểu đồ và chỉ số được hiển thị theo từng lần huấn luyện; mặc định chọn lần đã hoàn thành gần nhất và vẫn có thể xem lại lịch sử.",
    )

    try:
        runs = client.training_runs(status="COMPLETED", limit=50).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    if not runs:
        st.info("Chưa có lần huấn luyện nào đã hoàn thành.")
        return

    labels = {
        f"{row['business_date']} | {row['run_id']}": row["run_id"]
        for row in runs
    }
    selected = st.selectbox("Lần huấn luyện", list(labels))
    run_id = labels[selected]

    try:
        result = client.training_results(run_id)
        departments = client.departments()
    except ApiClientError as exc:
        show_api_error(exc)
        return

    run = result.get("run", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Số mẫu", run.get("row_count") or "-")
    c2.metric("Khoa", run.get("department_count") or "-")
    c3.metric("Số mô hình ứng viên", run.get("completed_candidate_count") or "-")
    c4.metric("Phiên bản đặc trưng", run.get("feature_version") or "-")

    recommendations = result.get("recommendations", [])
    st.subheader("Khuyến nghị mô hình")
    dataframe([
        {**row, "policy": {k: v for k, v in (row.get("policy") or {}).items() if k != "comparison"}}
        for row in recommendations
    ], height=220)

    horizon = st.radio(
        "Mốc dự báo phân tích",
        [1, 3],
        horizontal=True,
        format_func=lambda h: f"H+{h}",
    )

    comparison_status = render_comparison(recommendations, horizon)

    candidates_all = result.get("candidates", [])
    candidates = candidate_rows_for_horizon(candidates_all, horizon)
    enriched_department_metrics = enrich_department_metrics(
        result.get("department_metrics", []),
        candidates_all,
    )

    st.subheader("So sánh chỉ số đánh giá giữa các mô hình")
    metric_name = st.selectbox("Chỉ số đánh giá", list(TRAINING_METRICS))
    if comparison_status:
        st.caption("Các chỉ số và biểu đồ bên dưới là đánh giá test gốc của lần huấn luyện, tách biệt với backtest chung ở trên.")
    metric_meta = TRAINING_METRICS[metric_name]
    metric_key = str(metric_meta["key"])
    scale = float(metric_meta.get("scale", 1.0))
    unit = str(metric_meta.get("unit") or "")

    scope_options = {"Toàn bộ hệ thống": None}
    for dept in departments:
        scope_options[
            f"Khoa {dept['department_id']} - {dept['department_name']}"
        ] = int(dept["department_id"])
    scope_label = st.selectbox("Phạm vi đánh giá", list(scope_options))
    metric_department_id = scope_options[scope_label]

    metric_source = (
        candidates_all
        if metric_department_id is None
        else enriched_department_metrics
    )
    metric_rows = metric_comparison_rows(
        metric_source,
        horizon=horizon,
        metric_key=metric_key,
        department_id=metric_department_id,
    )
    if metric_rows:
        chart_df = pd.DataFrame(metric_rows)
        chart_df["value"] = (
            chart_df["value"].astype(float) * scale
        )
        chart_df = chart_df.rename(
            columns={
                "model_family": "Mô hình",
                "value": metric_name,
            }
        )
        chart_df = chart_df.set_index(
            "Mô hình"
        )
        st.bar_chart(
            chart_df[[metric_name]]
        )
        st.caption(
            f"{metric_name} ({unit or 'không đơn vị'}). {_metric_help(metric_meta)}"
        )
    else:
        st.info("Không có chỉ số đánh giá phù hợp với lựa chọn hiện tại.")

    with st.expander("Bảng chỉ số toàn hệ thống"):
        dataframe(candidates, height=280)

    with st.expander("Bảng chỉ số theo khoa"):
        dataframe(
            [
                row
                for row in enriched_department_metrics
                if int(row.get("horizon") or 0) == horizon
            ],
            height=320,
        )

    st.divider()
    st.subheader("Đánh giá trên tập kiểm tra – biểu đồ theo từng ngày")

    model_families = [
        str(row["model_family"])
        for row in candidates
        if row.get("model_family")
    ]
    if not model_families:
        st.info("Lần huấn luyện này chưa có mô hình ứng viên cho mốc dự báo đã chọn.")
        return

    evaluation_model = st.selectbox(
        "Mô hình dùng để đánh giá",
        model_families,
    )
    department_map = {
        f"{row['department_id']} - {row['department_name']}": int(row["department_id"])
        for row in departments
    }
    if not department_map:
        st.info("Chưa có khoa hoạt động để xem đánh giá theo ngày. Các chỉ số tổng hợp vẫn được hiển thị ở trên.")
        return
    evaluation_department_label = st.selectbox(
        "Khoa cần đánh giá",
        list(department_map),
    )
    evaluation_department_id = department_map[evaluation_department_label]

    try:
        evaluation = client.training_evaluation(
            run_id=run_id,
            horizon=horizon,
            model_family=evaluation_model,
            department_id=evaluation_department_id,
        )
    except ApiClientError as exc:
        show_api_error(exc)
        return

    split = evaluation.get("split", {})
    rows = evaluation.get("rows", [])

    st.markdown("#### 1. Dòng thời gian chia tập huấn luyện / kiểm tra")
    st.altair_chart(
        _timeline_chart(split),
    )
    st.caption(
        "Dữ liệu được chia theo thời gian của ngày cần dự báo, không xáo trộn thứ tự. Tập kiểm tra được giữ riêng theo lịch sử và không dùng mô hình đang vận hành để dự báo ngược lại tập kiểm tra."
    )

    chart_rows = evaluation_chart_frame(rows)
    if chart_rows:
        frame = pd.DataFrame(chart_rows)
        frame["target_date"] = pd.to_datetime(
            frame["target_date"]
        )
        frame = (
            frame
            .sort_values("target_date")
            .set_index("target_date")
            .rename_axis("Ngày cần dự báo")
            .rename(
                columns={
                    "actual": "Thực tế",
                    "predicted": "Dự báo",
                    "residual": "Sai số",
                    "zero": "Mốc 0",
                }
            )
        )

        st.markdown(
            "#### 2. Thực tế và dự báo – "
            "Tập kiểm tra"
        )
        st.line_chart(
            frame[
                [
                    "Thực tế",
                    "Dự báo",
                ]
            ]
        )

        st.markdown(
            "#### 3. Sai số theo thời gian"
        )
        st.line_chart(
            frame[
                [
                    "Sai số",
                    "Mốc 0",
                ]
            ]
        )
        st.caption(
            "Sai số = Thực tế - Dự báo. Sai số > 0 nghĩa là mô hình dự báo thấp hơn thực tế; sai số < 0 nghĩa là mô hình dự báo cao hơn thực tế."
        )
    else:
        st.info("Không có dữ liệu dự báo chi tiết của tập kiểm tra cho lựa chọn hiện tại.")

    st.markdown("#### Xếp hạng mô hình")
    dataframe(
        [
            row
            for row in result.get("rankings", [])
            if int(row.get("horizon", 0)) == horizon
        ],
        height=240,
    )
    if comparison_status == "COMPLETED":
        st.caption("Xếp hạng theo sai số gộp của các cửa sổ backtest chung; không dùng kỳ kiểm chứng riêng.")
    elif comparison_status == "INSUFFICIENT_DATA":
        st.caption("Xếp hạng test gốc để tham khảo; chưa có so sánh hợp lệ với mô hình tham chiếu.")
