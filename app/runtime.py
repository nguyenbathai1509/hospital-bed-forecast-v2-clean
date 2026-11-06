from __future__ import annotations

import streamlit as st

from app.api_client import HospitalApiClient
from app.config import load_ui_settings


@st.cache_resource
def get_api_client() -> HospitalApiClient:
    settings = load_ui_settings()
    return HospitalApiClient(
        settings.api_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )