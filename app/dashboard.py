from __future__ import annotations

import streamlit as st

from app.api_client import ApiClientError
from app.config import load_ui_settings
from app.pages import data, demo_reset, forecast, models, monitoring, overview, training, training_results
from app.runtime import get_api_client
from app.styles import apply_global_styles, sidebar_brand, sidebar_meta, sidebar_note


st.set_page_config(
    page_title="Dự báo giường bệnh V2",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


PAGES = {
    "\U0001f3e0 T\u1ed5ng quan": overview.render,
    "\U0001f4c2 D\u1eef li\u1ec7u": data.render,
    "\U0001f9e0 Hu\u1ea5n luy\u1ec7n m\u00f4 h\u00ecnh": training.render,
    "\U0001f4ca K\u1ebft qu\u1ea3 hu\u1ea5n luy\u1ec7n": training_results.render,
    "\U0001f3c6 Qu\u1ea3n l\u00fd m\u00f4 h\u00ecnh": models.render,
    "\U0001f52e D\u1ef1 b\u00e1o": forecast.render,
    "\U0001f4c8 Gi\u00e1m s\u00e1t": monitoring.render,
    "\U0001f9f9 \u0110\u1eb7t l\u1ea1i tr\u00ecnh di\u1ec5n": demo_reset.render,
}


def main() -> None:
    settings = load_ui_settings()
    client = get_api_client()
    apply_global_styles()

    with st.sidebar:
        sidebar_brand(
            "D\u1ef0 B\u00c1O GI\u01af\u1edcNG B\u1ec6NH",
            (
                "\u0110i\u1ec1u h\u01b0\u1edbng theo quy tr\u00ecnh: "
                "D\u1eef li\u1ec7u \u2192 Hu\u1ea5n luy\u1ec7n \u2192 "
                "\u0110\u00e1nh gi\u00e1 \u2192 Qu\u1ea3n l\u00fd m\u00f4 h\u00ecnh "
                "\u2192 D\u1ef1 b\u00e1o \u2192 Gi\u00e1m s\u00e1t."
            ),
        )

        page = st.radio(
            "\u0110i\u1ec1u h\u01b0\u1edbng",
            list(PAGES),
            key="hb-navigation",
            label_visibility="collapsed",
        )

        st.divider()

        sidebar_meta("D\u1ecbch v\u1ee5 h\u1ec7 th\u1ed1ng", settings.api_base_url)
        sidebar_note(
            "Ch\u1ebf \u0111\u1ed9 hi\u1ec7n t\u1ea1i: "
            "M\u00e1y c\u1ee5c b\u1ed9 / N\u1ed9i b\u1ed9."
        )

        if st.button(
            "Ki\u1ec3m tra k\u1ebft n\u1ed1i h\u1ec7 th\u1ed1ng",
            use_container_width=True,
        ):
            try:
                health = client.health()
                st.success(
                    "K\u1ebft n\u1ed1i th\u00e0nh c\u00f4ng | "
                    f"Tr\u1ea1ng th\u00e1i: {health.get('status')} | "
                    f"Phi\u00ean b\u1ea3n: {health.get('api_version')}"
                )
            except ApiClientError as exc:
                st.error(
                    "Kh\u00f4ng th\u1ec3 k\u1ebft n\u1ed1i h\u1ec7 th\u1ed1ng: "
                    f"{exc.code}: {exc.message}"
                )

    with client.request_scope():
        PAGES[page](client)


if __name__ == "__main__":
    main()
