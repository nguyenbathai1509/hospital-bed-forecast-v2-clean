from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error, status_text


PROMOTION_CONFIRMATION = "I_CONFIRM_PROMOTION"
ROLLBACK_CONFIRMATION = "I_CONFIRM_EMERGENCY_ROLLBACK"


def render(client: HospitalApiClient) -> None:
    page_header(
        "🏆 Quản lý mô hình",
        "Theo dõi mô hình đang sử dụng, mô hình khuyến nghị, lựa chọn mô hình và khôi phục khi cần.",
    )

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

        st.success(
            "Đưa mô hình vào sử dụng: "
            f"{status_text(completed_status)}"
        )

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
                "Production hiện tại",
                active_family,
            )

            c2.metric(
                "Recommended",
                recommended_family,
            )

            c3.metric(
                "Daily Lock",
                (
                    "ĐÃ KHÓA"
                    if locked
                    else "CHƯa KHÓA"
                ),
            )

            c4.metric(
                "Promotion hôm nay",
                (
                    "ĐÃ DÙNG"
                    if quota_used
                    else "CÒN 1 LẦN"
                ),
            )

            if scheduled:
                st.info(
                    "SCHEDULED cho chu kỳ tiếp theo: "
                    f"{scheduled_family} | "
                    "effective_from="
                    f"{scheduled.get('effective_from_business_date')}"
                )

            if locked:
                st.warning(
                    "🔒 Chu kỳ hiện tại đã được "
                    f"dự báo bằng {lock_family}. "
                    f"Origin date: {lock.get('origin_date')}. "
                    "Model của chu kỳ này không được "
                    "thay đổi."
                )

                st.caption(
                    "Candidate đã khóa: "
                    f"{lock.get('model_candidate_id')} | "
                    "trigger_department="
                    f"{lock.get('trigger_department_id')}"
                )

            if quota_used:
                if locked:
                    st.error(
                        f"H+{horizon} đã dùng NORMAL Promotion "
                        "của business_date hiện tại "
                        "và đã có Daily Model Lock. "
                        "Không thể Promotion thường thêm "
                        "cho horizon này trong ngày."
                    )
                else:
                    st.warning(
                        f"H+{horizon} đã dùng NORMAL Promotion "
                        "của business_date hiện tại. "
                        f"Model đã chọn là {active_family}. "
                        "Chưa có Daily Model Lock nhưng quota "
                        "Promotion hôm nay đã hết."
                    )

                st.write(
                    "**Model đang được giữ: "
                    f"{active_family}**"
                )

                continue

            if locked:
                st.info(
                    "Daily Model Lock chỉ khóa chu kỳ "
                    "hiện tại. Quota Promotion của H+"
                    f"{horizon} vẫn còn. "
                    "Nếu chọn model khác, backend sẽ "
                    "lập kế hoạch NEXT_CYCLE."
                )
            elif active:
                st.info(
                    "Horizon này đã có Production "
                    f"{active_family} nhưng chưa có Daily Lock. "
                    "Nếu quota còn, bạn vẫn có thể "
                    "chọn model khác trước khi dự báo."
                )
            else:
                st.info(
                    "Chưa có Production cho horizon này. "
                    "Recommended được chọn sẵn "
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
                st.error(
                    "Không tìm thấy Recommended candidate "
                    f"cho H+{horizon} trong Model Registry."
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
                    "Không có candidate hợp lệ "
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
                f"Đưa H+{horizon} vào kế hoạch Promotion",
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
                    marks.append("LOCKED")

                if candidate_id == _active:
                    marks.append("ACTIVE")

                if candidate_id == _scheduled:
                    marks.append("SCHEDULED")

                if candidate_id == _recommended:
                    marks.append("Recommended")

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
                    "Candidate dùng để "
                    f"Promotion H+{horizon}",
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
                        "⚠ Manual Override: "
                        f"H+{horizon} sẽ Promotion "
                        f"{selected_row.get('model_family')} "
                        "thay vì Recommended "
                        f"{recommended_family}."
                    )
                else:
                    st.caption(
                        "Đang dùng candidate "
                        "Recommended cho kế hoạch."
                    )

            elif active_candidate_id:
                st.caption(
                    "Dropdown đang hiển thị model "
                    "thực tế hiện tại. "
                    "Tick checkbox nếu muốn tạo "
                    "một kế hoạch Promotion mới."
                )

    reason = st.text_input(
        "Lý do Promotion",
        value=(
            "Promote selected model(s) "
            "to Production from Streamlit."
        ),
        max_chars=1000,
    )

    current_request = {
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
        "XEM KẾ HOẠCH PROMOTION",
        disabled=not can_preview,
    ):
        try:
            plan = client.promote_models(
                horizons=(
                    requested_horizons
                ),
                candidate_ids=(
                    candidate_ids
                ),
                requested_by=(
                    "streamlit"
                ),
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
            "#### Kế hoạch Promotion"
        )

        st.json(plan)

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
                "Hãy bấm XEM KẾ HOẠCH PROMOTION "
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
                "để commit Promotion",
                type="password",
                key=(
                    "promotion_confirmation"
                ),
            )

            confirm_disabled = (
                typed
                != PROMOTION_CONFIRMATION
                or request_changed
                or not isinstance(
                    snapshot,
                    dict,
                )
            )

            if st.button(
                "XÁC NHẬN PROMOTION",
                disabled=(
                    confirm_disabled
                ),
            ):
                try:
                    committed = (
                        client.promote_models(
                            horizons=[
                                int(h)
                                for h in snapshot[
                                    "horizons"
                                ]
                            ],
                            candidate_ids=dict(
                                snapshot[
                                    "candidate_ids"
                                ]
                            ),
                            requested_by=(
                                "streamlit"
                            ),
                            reason=str(
                                snapshot[
                                    "reason"
                                ]
                            ),
                            confirmation=typed,
                        )
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

    st.subheader("Emergency Rollback")
    rollback_horizon = st.selectbox("Rollback horizon", [1, 3], format_func=lambda h: f"H+{h}")
    rollback_reason = st.text_input(
        "Lý do rollback (audit)",
        value="Emergency rollback requested from Streamlit UI.",
        max_chars=1000,
    )
    if st.button("KIỂM TRA ROLLBACK"):
        try:
            rollback_plan = client.rollback_model(
                horizon=int(rollback_horizon),
                requested_by="streamlit",
                reason=rollback_reason,
                confirmation=None,
            )
            st.session_state["rollback_plan"] = rollback_plan
        except ApiClientError as exc:
            show_api_error(exc)

    rollback_plan = st.session_state.get("rollback_plan")
    if isinstance(rollback_plan, dict):
        st.json(rollback_plan)
        if rollback_plan.get("status") == "CONFIRMATION_REQUIRED":
            typed = st.text_input(
                f"Gõ `{ROLLBACK_CONFIRMATION}` để commit Emergency Rollback",
                type="password",
                key="rollback_confirmation",
            )
            if st.button("XÁC NHẬN EMERGENCY ROLLBACK", disabled=typed != ROLLBACK_CONFIRMATION):
                try:
                    committed = client.rollback_model(
                        horizon=int(rollback_horizon),
                        requested_by="streamlit",
                        reason=rollback_reason,
                        confirmation=typed,
                    )
                    st.success(f"Rollback: {committed.get('status')}")
                    st.json(committed)
                except ApiClientError as exc:
                    show_api_error(exc)