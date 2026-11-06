from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError, HospitalApiClient
from app.components import dataframe, page_header, show_api_error


PROMOTION_CONFIRMATION = "I_CONFIRM_PROMOTION"
ROLLBACK_CONFIRMATION = "I_CONFIRM_EMERGENCY_ROLLBACK"


def render(client: HospitalApiClient) -> None:
    page_header(
        "🏆 Model Registry",
        "Production, Candidates, Recommendation, Promote và Rollback. Recommended không đồng nghĩa Production.",
    )

    try:
        production = client.production_models()
        models = client.models(limit=200).get("rows", [])
    except ApiClientError as exc:
        show_api_error(exc)
        return

    st.subheader("Production state")
    for state in production.get("horizons", []):
        active = state.get("active") or {}
        scheduled = state.get("scheduled") or {}
        recommendation = state.get("recommendation") or {}
        lock = state.get("daily_lock") or {}
        with st.container(border=True):
            st.write(f"### H+{state.get('horizon')}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("ACTIVE", active.get("model_family", "-"))
            c2.metric("SCHEDULED", scheduled.get("model_family", "-"))
            c3.metric("Recommended", recommendation.get("recommended_family", "-"))
            c4.metric("Action", recommendation.get("action", "-"))
            if lock:
                st.caption(
                    f"Daily Model Lock: {lock.get('model_family')} | origin={lock.get('origin_date')} | "
                    f"trigger_department={lock.get('trigger_department_id')}"
                )

    st.subheader("Model Registry")
    horizon_filter = st.selectbox("Horizon filter", ["ALL", 1, 3])
    family_filter = st.selectbox("Family filter", ["ALL", "RF", "XGBOOST", "SVR", "LSTM"])
    filtered = [
        row
        for row in models
        if (horizon_filter == "ALL" or int(row["horizon"]) == horizon_filter)
        and (family_filter == "ALL" or row["model_family"] == family_filter)
    ]
    dataframe(filtered, height=350)

    st.subheader("Promotion")
    st.warning(
        "Promotion là thay đổi Production thật. "
        "Recommended chỉ là lựa chọn mặc định; "
        "bạn có thể chọn candidate khác trong cùng Training Run. "
        "Luôn xem kế hoạch trước khi xác nhận."
    )

    horizons = st.multiselect(
        "Horizon cần xét Promotion",
        [1, 3],
        default=[1, 3],
        format_func=lambda h: f"H+{h}",
    )

    production_by_horizon = {
        int(state["horizon"]): state
        for state in production.get("horizons", [])
        if state.get("horizon") is not None
    }

    candidate_ids: dict[str, str] = {}
    selection_ready = True

    for horizon in horizons:
        horizon = int(horizon)

        state = (
            production_by_horizon.get(horizon)
            or {}
        )

        recommendation = (
            state.get("recommendation")
            or {}
        )

        recommended_candidate_id = (
            recommendation.get(
                "recommended_candidate_id"
            )
        )

        recommended_family = (
            recommendation.get(
                "recommended_family"
            )
            or "-"
        )

        recommended_row = next(
            (
                row
                for row in models
                if row.get("candidate_id")
                == recommended_candidate_id
            ),
            None,
        )

        with st.container(border=True):
            st.write(f"#### H+{horizon}")

            c1, c2 = st.columns(2)

            c1.metric(
                "Recommended",
                recommended_family,
            )

            if recommended_row is None:
                c2.metric(
                    "Training Run",
                    "-",
                )
                st.error(
                    f"Không tìm thấy Recommended candidate "
                    f"cho H+{horizon} trong Model Registry."
                )
                selection_ready = False
                continue

            recommended_run_id = (
                recommended_row.get("run_id")
            )

            c2.metric(
                "Training Run",
                recommended_run_id or "-",
            )

            eligible = [
                row
                for row in models
                if int(row.get("horizon", -1))
                == horizon
                and row.get("run_id")
                == recommended_run_id
                and row.get("registry_status")
                not in {"FAILED", "ARCHIVED"}
            ]

            eligible.sort(
                key=lambda row: (
                    0
                    if row.get("candidate_id")
                    == recommended_candidate_id
                    else 1,
                    float(
                        row.get("mae")
                        if row.get("mae") is not None
                        else 10**9
                    ),
                    str(row.get("model_family")),
                )
            )

            options = [
                str(row["candidate_id"])
                for row in eligible
            ]

            if not options:
                st.error(
                    f"Không có candidate hợp lệ "
                    f"cho H+{horizon}."
                )
                selection_ready = False
                continue

            if recommended_candidate_id in options:
                default_index = options.index(
                    recommended_candidate_id
                )
            else:
                default_index = 0

            rows_by_id = {
                str(row["candidate_id"]): row
                for row in eligible
            }

            def _candidate_label(
                candidate_id: str,
                *,
                _rows=rows_by_id,
                _recommended=(
                    recommended_candidate_id
                ),
            ) -> str:
                row = _rows[candidate_id]

                family = (
                    row.get("model_family")
                    or "-"
                )

                mae = row.get("mae")

                mae_text = (
                    "-"
                    if mae is None
                    else f"{float(mae):.4f}"
                )

                suffix = (
                    " | Recommended"
                    if candidate_id
                    == _recommended
                    else ""
                )

                return (
                    f"{family} | MAE={mae_text}"
                    f"{suffix}"
                )

            selected_candidate_id = (
                st.selectbox(
                    f"Candidate dùng để Promotion H+{horizon}",
                    options,
                    index=default_index,
                    format_func=_candidate_label,
                    key=(
                        f"promotion_candidate_h"
                        f"{horizon}"
                    ),
                )
            )

            candidate_ids[str(horizon)] = (
                selected_candidate_id
            )

            selected_row = (
                rows_by_id[
                    selected_candidate_id
                ]
            )

            if (
                selected_candidate_id
                != recommended_candidate_id
            ):
                st.warning(
                    "⚠ Manual Override: "
                    f"H+{horizon} đang chọn "
                    f"{selected_row.get('model_family')} "
                    "khác với Recommended "
                    f"{recommended_family}."
                )
            else:
                st.caption(
                    "Đang dùng lựa chọn mặc định "
                    "theo Recommendation."
                )

    reason = st.text_input(
        "Lý do Promotion",
        value=(
            "Promote selected model(s) "
            "to Production from Streamlit."
        ),
        max_chars=1000,
    )

    can_preview = (
        bool(horizons)
        and selection_ready
        and len(candidate_ids)
        == len(horizons)
    )

    if st.button(
        "XEM KẾ HOẠCH PROMOTION",
        disabled=not can_preview,
    ):
        try:
            requested_horizons = [
                int(h)
                for h in horizons
            ]

            requested_candidate_ids = {
                str(h): candidate_ids[str(h)]
                for h in requested_horizons
            }

            plan = client.promote_models(
                horizons=requested_horizons,
                candidate_ids=(
                    requested_candidate_ids
                ),
                requested_by="streamlit",
                reason=reason,
                confirmation=None,
            )

            st.session_state[
                "promotion_plan"
            ] = plan

            st.session_state[
                "promotion_request_snapshot"
            ] = {
                "horizons": (
                    requested_horizons
                ),
                "candidate_ids": (
                    requested_candidate_ids
                ),
                "reason": reason,
            }

        except ApiClientError as exc:
            show_api_error(exc)

    plan = st.session_state.get(
        "promotion_plan"
    )

    if isinstance(plan, dict):
        st.write("#### Kế hoạch Promotion")

        st.json(plan)

        snapshot = st.session_state.get(
            "promotion_request_snapshot"
        )

        if isinstance(snapshot, dict):
            st.caption(
                "Kế hoạch phía trên được tạo từ "
                "lựa chọn tại thời điểm bấm "
                "XEM KẾ HOẠCH PROMOTION. "
                "Nếu bạn đổi candidate sau đó, "
                "hãy xem kế hoạch lại trước khi xác nhận."
            )

        if (
            plan.get("status")
            == "CONFIRMATION_REQUIRED"
        ):
            typed = st.text_input(
                f"Gõ `{PROMOTION_CONFIRMATION}` "
                "để commit Promotion",
                type="password",
                key="promotion_confirmation",
            )

            if st.button(
                "XÁC NHẬN PROMOTION",
                disabled=(
                    typed
                    != PROMOTION_CONFIRMATION
                ),
            ):
                try:
                    if not isinstance(
                        snapshot,
                        dict,
                    ):
                        st.error(
                            "Không tìm thấy snapshot "
                            "của kế hoạch Promotion. "
                            "Hãy xem kế hoạch lại."
                        )
                    else:
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

                        st.success(
                            "Promotion: "
                            f"{committed.get('status')}"
                        )

                        st.json(committed)

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