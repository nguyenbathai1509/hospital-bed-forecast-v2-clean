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
        "Promotion là transaction thật. UI luôn gọi preview trước; chỉ exact confirmation phrase mới được commit."
    )
    horizons = st.multiselect("Horizon cần xét Promotion", [1, 3], default=[1, 3])
    reason = st.text_input(
        "Lý do Promotion",
        value="Promote recommended model(s) to Production from Streamlit.",
        max_chars=1000,
    )
    if st.button("XEM KẾ HOẠCH PROMOTION", disabled=not horizons):
        try:
            plan = client.promote_models(
                horizons=[int(h) for h in horizons],
                requested_by="streamlit",
                reason=reason,
                confirmation=None,
            )
            st.session_state["promotion_plan"] = plan
        except ApiClientError as exc:
            show_api_error(exc)

    plan = st.session_state.get("promotion_plan")
    if isinstance(plan, dict):
        st.json(plan)
        if plan.get("status") == "CONFIRMATION_REQUIRED":
            typed = st.text_input(
                f"Gõ `{PROMOTION_CONFIRMATION}` để commit Promotion",
                type="password",
                key="promotion_confirmation",
            )
            if st.button("XÁC NHẬN PROMOTION", disabled=typed != PROMOTION_CONFIRMATION):
                try:
                    committed = client.promote_models(
                        horizons=[int(h) for h in horizons],
                        requested_by="streamlit",
                        reason=reason,
                        confirmation=typed,
                    )
                    st.success(f"Promotion: {committed.get('status')}")
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