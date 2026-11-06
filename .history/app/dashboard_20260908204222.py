from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError
from app.config import load_ui_settings
from app.pages import data, forecast, models, monitoring, overview, training, training_results
from app.runtime import get_api_client


st.set_page_config(
    page_title="Hospital Bed Forecast V2",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


PAGES = {
    "🏠 Tổng quan": overview.render,
    "📂 Dữ liệu": data.render,
    "🔮 Dự báo": forecast.render,
    "🧠 Huấn luyện": training.render,
    "📊 Kết quả Training": training_results.render,
    "🏆 Model Registry": models.render,
    "📈 Monitoring": monitoring.render,
}


def main() -> None:
    settings = load_ui_settings()
    client = get_api_client()

    with st.sidebar:
        st.header("🏥 Hospital Bed Forecast V2")
        page = st.radio("Menu", list(PAGES), label_visibility="collapsed")
        st.divider()
        st.caption(f"FastAPI: `{settings.api_base_url}`")
        st.caption("Mode hiện tại: local/internal — Roles/Permissions sẽ làm ở bước tiếp theo.")
        if st.button("Kiểm tra API"):
            try:
                health = client.health()
                st.success(f"API {health.get('status')} | {health.get('api_version')}")
            except ApiClientError as exc:
                st.error(f"{exc.code}: {exc.message}")

    PAGES[page](client)


if __name__ == "__main__":
    main()