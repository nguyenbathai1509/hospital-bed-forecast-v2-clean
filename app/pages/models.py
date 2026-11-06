from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text, technical_details


PROMOTION_CONFIRMATION = "I_CONFIRM_PROMOTION"
ROLLBACK_CONFIRMATION = "I_CONFIRM_EMERGENCY_ROLLBACK"


def render(client: HospitalApiClient) -> None:
    page_header(
        "🏆 Quản lý mô hình",
        "Theo dõi mô hình đang sử dụng, mô hình khuyến nghị, lựa chọn mô hình và khôi phục khi cần.",
    )

    rollback_completed = st.session_state.pop("rollback_action_result", None)
    if rollback_completed is not None:
        for key in ("rollback_plan", "rollback_request_snapshot", "rollback_confirmation"):
            st.session_state.pop(key, None)
        message = f"Khôi phục mô hình: {status_text(rollback_completed.get('status'))}"
        if rollback_completed.get("status") == "COMPLETED":
            st.success(message)
        else:
            st.info(message)
        technical_details(rollback_completed, label="Chi tiết kỹ thuật của lần khôi phục")

    try:
        production = client.production_models()
        models = client.models(limit=200).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    st.subheader("Trạng thái mô hình đang sử dụng")
    for state in production.get("horizons", []):
        active = state.get("active") or {}
        scheduled = state.get("scheduled") or {}
        recommendation = state.get("recommendation") or {}
        lock = state.get("daily_lock") or {}
        with st.container(border=True):
            st.write(f"### H+{state.get('horizon')}")
            quota_used = bool(
                state.get(
                    "normal_change_quota_used",
                    False,
                )
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "ĐANG SỬ DỤNG",
                active.get("model_family", "-"),
            )

            c2.metric(
                "ĐÃ LÊN LỊCH",
                scheduled.get("model_family", "-"),
            )

            c3.metric(
                "Khuyến nghị",
                recommendation.get(
                    "recommended_family",
                    "-",
                ),
            )

            c4.metric(
                "Quyền đổi mô hình hôm nay",
                (
                    "ĐÃ DÙNG"
                    if quota_used
                    else "CÒN 1 LẦN"
                ),
            )

            st.caption(
                "Hành động khuyến nghị: "
                f"{recommendation.get('action', '-')}"
            )

            if lock:
                st.warning(
                    "🔒 Khóa mô hình dự báo: "
                    f"{lock.get('model_family')} | "
                    f"ngày dữ liệu={lock.get('origin_date')} | "
                    "khoa tạo khóa="
                    f"{lock.get('trigger_department_id')}"
                )
            else:
                st.caption(
                    "Khóa mô hình dự báo: CHƯA CÓ"
                )

    st.subheader("Danh sách mô hình")
    horizon_filter = st.selectbox("Mốc dự báo", ["ALL", 1, 3], format_func=lambda x: "Tất cả" if x == "ALL" else f"H+{x}")
    family_filter = st.selectbox("Loại mô hình", ["ALL", "RF", "XGBOOST", "SVR", "LSTM"], format_func=lambda x: "Tất cả" if x == "ALL" else x)
    filtered = [
        row
        for row in models
        if (horizon_filter == "ALL" or int(row["horizon"]) == horizon_filter)
        and (family_filter == "ALL" or row["model_family"] == family_filter)
    ]
    dataframe(filtered, height=350)

    st.subheader("Đưa mô hình vào sử dụng")

    if st.session_state.pop(
        "promotion_just_completed",
        False,
    ):
        completed_status = (
            st.session_state.pop(
                "promotion_completed_status",
                "COMPLETED",
            )
        )

        st.session_state.pop(
            "promotion_plan",
            None,
        )

        st.session_state.pop(
            "promotion_request_snapshot",
            None,
        )

        st.session_state.pop(
            "promotion_confirmation",
            None,
        )

        message = f"Đưa mô hình vào sử dụng: {status_text(completed_status)}"
        if completed_status == "COMPLETED":
            st.success(message)
        else:
            st.info(message)

    st.warning(
        "Thao tác này thay đổi mô hình vận hành thật. "
        "Mô hình khuyến nghị chỉ là gợi ý mặc định. "
        "Mô hình đang sử dụng, mô hình đã lên lịch và khóa dự báo "
        "luôn được ưu tiên hiển thị."
    )

    production_by_horizon = {
        int(state["horizon"]): state
        for state
        in production.get(
            "horizons",
            [],
        )
        if state.get("horizon")
        is not None
    }

    requested_horizons: list[int] = []
    candidate_ids: dict[str, str] = {}

    selection_ready = True

    for horizon in (1, 3):
        state = (
            production_by_horizon.get(
                horizon
            )
            or {}
        )

        active = (
            state.get("active")
            or {}
        )

        scheduled = (
            state.get("scheduled")
            or {}
        )

        recommendation = (
            state.get("recommendation")
            or {}
        )

        lock = (
            state.get("daily_lock")
            or {}
        )

        quota_used = bool(
            state.get(
                "normal_change_quota_used",
                False,
            )
        )

        active_family = (
            active.get("model_family")
            or "-"
        )

        scheduled_family = (
            scheduled.get("model_family")
            or "-"
        )

        recommended_family = (
            recommendation.get(
                "recommended_family"
            )
            or "-"
        )

        recommended_candidate_id = (
            recommendation.get(
                "recommended_candidate_id"
            )
        )

        lock_family = (
            lock.get("model_family")
            or "-"
        )

        locked = bool(lock)

        with st.container(border=True):
            title = (
                f"H+{horizon} "
                + (
                    "🔒 ĐÃ KHÓA"
                    if locked
                    else ""
                )
            )

            st.write(
                f"#### {title}"
            )

            c1, c2, c3, c4 = (
                st.columns(4)
            )

            c1.metric(
                "Mô hình đang sử dụng",
                active_family,
            )

            c2.metric(
                "Khuyến nghị",
                recommended_family,
            )

            c3.metric(
                "Khóa dự báo",
                (
                    "ĐÃ KHÓA"
                    if locked
                    else "CHƯA KHÓA"
                ),
            )

            c4.metric(
                "Quyền đổi mô hình hôm nay",
                (
                    "ĐÃ DÙNG"
                    if quota_used
                    else "CÒN 1 LẦN"
                ),
            )

            if scheduled:
                st.info(
                    "Mô hình đã lên lịch cho chu kỳ tiếp theo: "
                    f"{scheduled_family} | "
                    "áp dụng từ ngày="
                    f"{scheduled.get('effective_from_business_date')}"
                )

            if locked:
                st.warning(
                    "🔒 Chu kỳ hiện tại đã được "
                    f"dự báo bằng {lock_family}. "
                    f"Ngày dữ liệu: {lock.get('origin_date')}. "
                    "Mô hình của chu kỳ này không được "
                    "thay đổi."
                )

                st.caption(
                    "Mã mô hình đã khóa: "
                    f"{lock.get('model_candidate_id')} | "
                    "khoa tạo khóa="
                    f"{lock.get('trigger_department_id')}"
                )

            if quota_used:
                if locked:
                    st.error(
                        f"H+{horizon} đã sử dụng quyền đổi mô hình "
                        "của ngày dữ liệu hiện tại "
                        "và mô hình của chu kỳ hiện tại đã được khóa sau khi tạo dự báo. "
                        "Không thể đổi sang mô hình khác bằng quy trình thông thường "
                        "cho mốc dự báo này trong ngày."
                    )
                else:
                    st.warning(
                        f"H+{horizon} đã sử dụng quyền đổi mô hình "
                        "trong ngày dữ liệu hiện tại. "
                        f"Mô hình đã chọn là {active_family}. "
                        "Chưa tạo dự báo bằng mô hình này, nhưng quyền đổi mô hình "
                        "hôm nay đã được sử dụng. Bạn không thể đổi sang mô hình khác trong ngày hiện tại."
                    )

                st.write(
                    "**Mô hình đang sử dụng: "
                    f"{active_family}**"
                )

                continue

            if locked:
                st.info(
                    "Khóa dự báo chỉ giữ nguyên mô hình của chu kỳ "
                    "hiện tại. Quyền đổi mô hình của H+"
                    f"{horizon} vẫn còn. "
                    "Nếu chọn mô hình khác, hệ thống sẽ "
                    "lên lịch mô hình đó cho chu kỳ tiếp theo."
                )
            elif active:
                st.info(
                    "Mốc dự báo này đang sử dụng mô hình "
                    f"{active_family} nhưng chưa tạo dự báo. "
                    "Vì quyền đổi mô hình hôm nay vẫn còn, bạn có thể "
                    "chọn mô hình khác trước khi tạo dự báo."
                )
            else:
                st.info(
                    "Chưa có mô hình đang sử dụng cho mốc dự báo này. "
                    "Mô hình khuyến nghị được chọn sẵn "
                    "nhưng bạn có thể thay đổi."
                )

            recommended_row = next(
                (
                    row
                    for row in models
                    if row.get(
                        "candidate_id"
                    )
                    == recommended_candidate_id
                ),
                None,
            )

            if recommended_row is None:
                if not recommended_candidate_id:
                    st.info(f"Chưa có mô hình khuyến nghị cho H+{horizon}. Hãy hoàn tất huấn luyện và xem Kết quả huấn luyện trước.")
                else:
                    st.error(
                        "Không tìm thấy mô hình ứng viên được khuyến nghị "
                        f"cho H+{horizon} trong danh sách mô hình."
                    )

                selection_ready = False
                continue

            recommended_run_id = (
                recommended_row.get(
                    "run_id"
                )
            )

            eligible = [
                row
                for row in models
                if int(
                    row.get(
                        "horizon",
                        -1,
                    )
                )
                == horizon
                and row.get("run_id")
                == recommended_run_id
                and row.get(
                    "registry_status"
                )
                not in {
                    "FAILED",
                    "ARCHIVED",
                }
            ]

            rows_by_id = {
                str(
                    row["candidate_id"]
                ): row
                for row in eligible
            }

            options = list(
                rows_by_id
            )

            if not options:
                st.error(
                    "Không có mô hình ứng viên hợp lệ "
                    f"cho H+{horizon}."
                )

                selection_ready = False
                continue

            lock_candidate_id = (
                lock.get(
                    "model_candidate_id"
                )
            )

            active_candidate_id = (
                active.get(
                    "candidate_id"
                )
            )

            scheduled_candidate_id = (
                scheduled.get(
                    "candidate_id"
                )
            )

            preferred = [
                lock_candidate_id,
                active_candidate_id,
                scheduled_candidate_id,
                recommended_candidate_id,
            ]

            default_candidate_id = next(
                (
                    candidate_id
                    for candidate_id
                    in preferred
                    if candidate_id
                    in rows_by_id
                ),
                options[0],
            )

            options.sort(
                key=lambda candidate_id: (
                    0
                    if candidate_id
                    == default_candidate_id
                    else 1,
                    float(
                        rows_by_id[
                            candidate_id
                        ].get("mae")
                        if rows_by_id[
                            candidate_id
                        ].get("mae")
                        is not None
                        else 10**9
                    ),
                )
            )

            default_index = (
                options.index(
                    default_candidate_id
                )
            )

            include = st.checkbox(
                f"Đưa H+{horizon} vào kế hoạch sử dụng mô hình",
                value=(
                    not bool(active)
                ),
                key=(
                    f"promotion_include_h"
                    f"{horizon}"
                ),
            )

            def _candidate_label(
                candidate_id: str,
                *,
                _rows=rows_by_id,
                _recommended=(
                    recommended_candidate_id
                ),
                _active=(
                    active_candidate_id
                ),
                _scheduled=(
                    scheduled_candidate_id
                ),
                _locked=(
                    lock_candidate_id
                ),
            ) -> str:
                row = _rows[
                    candidate_id
                ]

                family = (
                    row.get(
                        "model_family"
                    )
                    or "-"
                )

                mae = row.get("mae")

                mae_text = (
                    "-"
                    if mae is None
                    else f"{float(mae):.4f}"
                )

                marks = []

                if candidate_id == _locked:
                    marks.append("ĐÃ KHÓA")

                if candidate_id == _active:
                    marks.append("ĐANG SỬ DỤNG")

                if candidate_id == _scheduled:
                    marks.append("ĐÃ LÊN LỊCH")

                if candidate_id == _recommended:
                    marks.append("KHUYẾN NGHỊ")

                suffix = (
                    ""
                    if not marks
                    else " | "
                    + " | ".join(marks)
                )

                return (
                    f"{family} | "
                    f"MAE={mae_text}"
                    f"{suffix}"
                )

            selected_candidate_id = (
                st.selectbox(
                    "Mô hình ứng viên cho "
                    f"H+{horizon}",
                    options,
                    index=default_index,
                    format_func=(
                        _candidate_label
                    ),
                    disabled=not include,
                    key=(
                        "promotion_candidate_"
                        f"h{horizon}_"
                        f"{recommended_run_id}"
                    ),
                )
            )

            selected_row = (
                rows_by_id[
                    selected_candidate_id
                ]
            )

            if include:
                requested_horizons.append(
                    horizon
                )

                candidate_ids[
                    str(horizon)
                ] = (
                    selected_candidate_id
                )

                if (
                    selected_candidate_id
                    != recommended_candidate_id
                ):
                    st.warning(
                        "⚠ Chọn khác khuyến nghị: "
                        f"H+{horizon} sẽ sử dụng "
                        f"{selected_row.get('model_family')} "
                        "thay vì mô hình khuyến nghị "
                        f"{recommended_family}."
                    )
                else:
                    st.caption(
                        "Đang dùng mô hình "
                        "được khuyến nghị cho kế hoạch."
                    )

            elif active_candidate_id:
                st.caption(
                    "Danh sách đang hiển thị mô hình "
                    "thực tế hiện tại. "
                    "Đánh dấu ô phía trên nếu muốn tạo "
                    "một kế hoạch đổi mô hình mới."
                )

    reason = st.text_input(
        "Lý do thay đổi mô hình",
        value=(
            "Đưa mô hình đã chọn "
            "vào sử dụng từ giao diện."
        ),
        max_chars=1000,
    )

    current_request = {
        "production_state": production,
        "horizons": list(
            requested_horizons
        ),
        "candidate_ids": dict(
            candidate_ids
        ),
        "reason": reason,
    }

    can_preview = (
        bool(requested_horizons)
        and selection_ready
    )

    if st.button(
        "XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG",
        disabled=not can_preview,
    ) and can_preview:
        for key in ("promotion_plan", "promotion_request_snapshot", "promotion_confirmation"):
            st.session_state.pop(key, None)
        try:
            with st.spinner("Đang kiểm tra kế hoạch sử dụng mô hình…"):
                plan = client.promote_models(
                    horizons=requested_horizons,
                    candidate_ids=candidate_ids,
                    requested_by="streamlit",
                    reason=reason,
                    confirmation=None,
                )

            st.session_state[
                "promotion_plan"
            ] = plan

            st.session_state[
                "promotion_request_snapshot"
            ] = dict(
                current_request
            )

        except ApiClientError as exc:
            show_api_error(exc)

    plan = st.session_state.get(
        "promotion_plan"
    )

    snapshot = st.session_state.get(
        "promotion_request_snapshot"
    )

    if isinstance(plan, dict):
        st.write(
            "#### Kế hoạch đưa mô hình vào sử dụng"
        )

        st.write(
            f"Trạng thái kế hoạch: "
            f"**{status_text(plan.get('status'))}**"
        )

        display_request = (
            snapshot
            if isinstance(snapshot, dict)
            else current_request
        )

        display_horizons = (
            display_request.get(
                "horizons",
                [],
            )
        )

        display_candidate_ids = (
            display_request.get(
                "candidate_ids",
                {},
            )
        )

        display_reason = str(
            display_request.get(
                "reason",
                "",
            )
            or ""
        )

        if display_horizons:
            st.caption(
                "Mốc dự báo đã chọn: "
                + ", ".join(
                    f"H+{int(h)}"
                    for h in display_horizons
                )
            )

        if (
            isinstance(
                display_candidate_ids,
                dict,
            )
            and display_candidate_ids
        ):
            dataframe(
                [
                    {
                        "horizon": int(h),
                        "candidate_id": candidate_id,
                    }
                    for h, candidate_id
                    in display_candidate_ids.items()
                ],
                height=180,
            )

        if display_reason:
            st.caption(
                f"Lý do: {display_reason}"
            )

        technical_details(
            plan,
            label=(
                "Chi tiết kỹ thuật "
                "của kế hoạch"
            ),
        )

        request_changed = (
            isinstance(
                snapshot,
                dict,
            )
            and snapshot
            != current_request
        )

        if request_changed:
            st.warning(
                "Lựa chọn hiện tại đã khác "
                "với kế hoạch đang hiển thị. "
                "Hãy bấm XEM KẾ HOẠCH ĐƯA MÔ HÌNH VÀO SỬ DỤNG "
                "lại trước khi xác nhận."
            )

        elif isinstance(
            snapshot,
            dict,
        ):
            st.caption(
                "Kế hoạch trên khớp với "
                "lựa chọn hiện tại."
            )

        if (
            plan.get("status")
            == "CONFIRMATION_REQUIRED"
        ):
            typed = st.text_input(
                f"Gõ `{PROMOTION_CONFIRMATION}` "
                "để xác nhận đưa mô hình vào sử dụng",
                type="password",
                key=(
                    "promotion_confirmation"
                ),
            )

            confirm_disabled = (
                typed
                != PROMOTION_CONFIRMATION
                or request_changed
                or not can_preview
                or not isinstance(
                    snapshot,
                    dict,
                )
            )

            if st.button(
                "XÁC NHẬN ĐƯA MÔ HÌNH VÀO SỬ DỤNG",
                disabled=(
                    confirm_disabled
                ),
            ) and not confirm_disabled:
                try:
                    with st.spinner("Đang đưa mô hình vào sử dụng…"):
                        committed = client.promote_models(
                            horizons=[int(h) for h in snapshot["horizons"]],
                            candidate_ids=dict(snapshot["candidate_ids"]),
                            requested_by="streamlit",
                            reason=str(snapshot["reason"]),
                            confirmation=typed,
                        )

                    st.session_state[
                        "promotion_completed_status"
                    ] = committed.get(
                        "status",
                        "COMPLETED",
                    )

                    st.session_state[
                        "promotion_just_completed"
                    ] = True

                    st.rerun()

                except ApiClientError as exc:
                    show_api_error(exc)

    st.subheader("Khôi phục mô hình khẩn cấp")
    rollback_horizon = st.selectbox("Mốc dự báo cần khôi phục", [1, 3], format_func=lambda h: f"H+{h}")
    rollback_reason = st.text_input(
        "Lý do khôi phục (lưu vết)",
        value="Yêu cầu khôi phục mô hình khẩn cấp từ giao diện.",
        max_chars=1000,
    )
    rollback_request = {
        "horizon": int(rollback_horizon), "reason": rollback_reason,
        "production_state": production,
    }
    rollback_snapshot = st.session_state.get("rollback_request_snapshot")
    if rollback_snapshot is not None and rollback_snapshot != rollback_request:
        for key in ("rollback_plan", "rollback_request_snapshot", "rollback_confirmation"):
            st.session_state.pop(key, None)
        st.warning("Lựa chọn hoặc trạng thái mô hình đã thay đổi. Hãy kiểm tra lại kế hoạch khôi phục trước khi xác nhận.")
    if st.button("KIỂM TRA KẾ HOẠCH KHÔI PHỤC"):
        for key in ("rollback_plan", "rollback_request_snapshot", "rollback_confirmation"):
            st.session_state.pop(key, None)
        try:
            with st.spinner("Đang kiểm tra kế hoạch khôi phục…"):
                rollback_plan = client.rollback_model(
                    horizon=int(rollback_horizon),
                    requested_by="streamlit",
                    reason=rollback_reason,
                    confirmation=None,
                )
            st.session_state["rollback_plan"] = rollback_plan
            st.session_state["rollback_request_snapshot"] = rollback_request
        except ApiClientError as exc:
            show_api_error(exc)

    rollback_plan = st.session_state.get("rollback_plan")
    if isinstance(rollback_plan, dict):
        st.write(
            f"Trạng thái kế hoạch: "
            f"**{status_text(rollback_plan.get('status'))}**"
        )

        st.caption(
            "Kế hoạch khôi phục đã "
            "được hệ thống kiểm tra. "
            "Chỉ xác nhận khi đúng với "
            "thao tác bạn muốn thực hiện."
        )

        technical_details(
            rollback_plan,
            label=(
                "Chi tiết kỹ thuật "
                "của kế hoạch khôi phục"
            ),
        )

        if rollback_plan.get("status") == "CONFIRMATION_REQUIRED":
            typed = st.text_input(
                f"Gõ chính xác `{ROLLBACK_CONFIRMATION}` để xác nhận khôi phục khẩn cấp",
                type="password",
                key="rollback_confirmation",
            )
            snapshot = st.session_state.get("rollback_request_snapshot")
            confirm_disabled = typed != ROLLBACK_CONFIRMATION or snapshot != rollback_request
            if st.button("XÁC NHẬN KHÔI PHỤC KHẨN CẤP", disabled=confirm_disabled) and not confirm_disabled:
                try:
                    with st.spinner("Đang khôi phục mô hình…"):
                        committed = client.rollback_model(
                            horizon=snapshot["horizon"],
                            requested_by="streamlit",
                            reason=snapshot["reason"],
                            confirmation=typed,
                        )
                    st.session_state["rollback_action_result"] = committed
                    st.rerun()
                except ApiClientError as exc:
                    show_api_error(exc)
