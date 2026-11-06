from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import page_header, show_api_error


DEMO_RESET_CONFIRMATION = "RESET DEMO STATE"


GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Dữ liệu và xử lý dữ liệu",
        (
            "pipeline_runs",
            "raw_bed_daily",
            "clean_bed_daily",
            "data_quality_issues",
            "bed_features_daily",
            "ml_samples",
        ),
    ),
    (
        "Huấn luyện và đánh giá",
        (
            "api_training_jobs",
            "training_runs",
            "model_candidates",
            "model_metrics_by_department",
            "model_evaluation_predictions",
            "model_recommendations",
            "model_candidate_rankings",
        ),
    ),
    (
        "Mô hình vận hành và dự báo",
        (
            "production_models",
            "production_changes",
            "production_change_items",
            "daily_model_locks",
            "forecast_drafts",
            "official_forecasts",
        ),
    ),
    (
        "Giám sát",
        (
            "official_actual_matches",
            "production_monitoring_runs",
            "production_monitoring_metrics",
        ),
    ),
)


def _group_total(
    counts: dict[str, int],
    names: tuple[str, ...],
) -> int:
    return sum(
        int(counts.get(name, 0) or 0)
        for name in names
    )


def render(client: HospitalApiClient) -> None:
    # Streamlit kh?ng cho s?a state c?a widget sau khi widget ??
    # ???c t?o trong c?ng l??t render. V? v?y sau reset th?nh c?ng,
    # ta rerun r?i cleanup widget state ? ??u l??t render k? ti?p.
    if st.session_state.pop("demo_reset_just_completed", False):
        st.session_state.pop("demo_reset_ack", None)
        st.session_state.pop("demo_reset_confirmation", None)

    page_header(
        "🧹 Đặt lại trình diễn",
        (
            "Đưa dữ liệu vận hành về trạng thái ban đầu để trình diễn "
            "toàn bộ quy trình từ xử lý dữ liệu → huấn luyện → chọn mô hình "
            "→ dự báo → xác nhận chính thức → giám sát."
        ),
    )

    st.error(
        "Đây là chức năng quản trị phục vụ trình diễn. "
        "Khi được bật, thao tác xác nhận sẽ XÓA dữ liệu vận hành "
        "khỏi cơ sở dữ liệu hiện tại."
    )

    try:
        status = client.demo_reset_status()
    except ApiClientError as exc:
        show_api_error(exc)
        return

    enabled = bool(status.get("enabled"))
    clean = bool(status.get("clean"))
    busy = bool(status.get("busy"))

    counts = status.get("counts") or {}
    retained = status.get("retained") or {}
    busy_counts = status.get("busy_counts") or {}

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Chức năng đặt lại",
        "ĐÃ BẬT" if enabled else "ĐANG KHÓA",
    )
    c2.metric(
        "Trạng thái dữ liệu",
        "SẠCH" if clean else "ĐÃ CÓ DỮ LIỆU",
    )
    c3.metric(
        "Tiến trình đang chạy",
        "CÓ" if busy else "KHÔNG",
    )
    c4.metric(
        "Khoa cấu hình được giữ lại",
        int(retained.get("departments", 0) or 0),
    )

    if not enabled:
        st.warning(
            "Chức năng đặt lại hiện đang bị khóa bởi dịch vụ hệ thống. "
            "Đây là trạng thái an toàn mặc định."
        )

    if busy:
        st.warning(
            "Không thể đặt lại vì quá trình xử lý dữ liệu, huấn luyện hoặc giám sát "
            "đang hoạt động."
        )

    if clean:
        st.success(
            "Trạng thái vận hành hiện đã sạch. "
            "Không cần đặt lại thêm."
        )

    st.subheader("Trạng thái dữ liệu sẽ bị xóa")

    group_columns = st.columns(len(GROUPS))

    for column, (label, table_names) in zip(
        group_columns,
        GROUPS,
        strict=True,
    ):
        with column:
            st.metric(
                label,
                _group_total(
                    counts,
                    table_names,
                ),
            )

    with st.expander(
        "Xem số dòng chi tiết theo bảng",
        expanded=False,
    ):
        rows = [
            {
                "table": table_name,
                "row_count": int(row_count),
            }
            for table_name, row_count in counts.items()
        ]

        if rows:
            st.dataframe(
                rows,
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "Không có dữ liệu vận hành trong trạng thái trả về."
            )

    st.subheader("Dữ liệu hệ thống được giữ lại")

    r1, r2 = st.columns(2)

    r1.metric(
        "Danh mục khoa",
        int(retained.get("departments", 0) or 0),
        help=(
            "Danh mục khoa được giữ lại để hệ thống vẫn biết "
            "các khoa đã cấu hình."
        ),
    )

    r2.metric(
        "Lịch sử cấu trúc dữ liệu",
        int(retained.get("schema_migrations", 0) or 0),
        help=(
            "Lịch sử thay đổi cấu trúc cơ sở dữ liệu được giữ nguyên."
        ),
    )

    with st.expander(
        "Kiểm tra tiến trình nền",
        expanded=False,
    ):
        st.json(busy_counts)

    st.divider()

    st.subheader("Xác nhận đặt lại")

    st.write(
        "Chỉ thực hiện thao tác này trước khi bắt đầu kịch bản trình diễn. "
        "Sau khi đặt lại, bạn sẽ thực hiện lại toàn bộ quy trình trên giao diện."
    )

    acknowledgement = st.checkbox(
        (
            "Tôi hiểu thao tác này sẽ xóa lịch sử xử lý dữ liệu, dữ liệu đã xử lý, "
            "kết quả huấn luyện, quản lý mô hình, mô hình vận hành, dự báo và giám sát "
            "hiện tại."
        ),
        key="demo_reset_ack",
    )

    typed = st.text_input(
        (
            f"Gõ chính xác `{DEMO_RESET_CONFIRMATION}` "
            "để mở khóa nút đặt lại"
        ),
        type="password",
        key="demo_reset_confirmation",
    )

    reset_allowed = (
        enabled
        and not busy
        and not clean
        and acknowledgement
        and typed == DEMO_RESET_CONFIRMATION
    )

    if st.button(
        "ĐẶT LẠI TOÀN BỘ TRẠNG THÁI TRÌNH DIỄN",
        type="primary",
        disabled=not reset_allowed,
        use_container_width=True,
    ):
        try:
            result = client.reset_demo(
                confirmation=typed,
            )
        except ApiClientError as exc:
            show_api_error(exc)
            return

        if (
            result.get("status") == "RESET_COMPLETED"
            and result.get("clean") is True
        ):
            st.success(
                "Đã đặt lại trạng thái trình diễn thành công."
            )

            st.json(result)

            # Ch? ??t m?t c? KH?NG thu?c widget.
            # Vi?c x?a state c?a checkbox/text_input s? di?n ra
            # ? ??u l??t render k? ti?p.
            st.session_state["demo_reset_just_completed"] = True

            st.rerun()

    st.caption(
        "Chức năng đặt lại không xóa lịch sử cấu trúc dữ liệu và không xóa "
        "danh mục khoa."
    )
