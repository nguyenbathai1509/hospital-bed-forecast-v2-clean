from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class UiSettings:
    api_base_url: str
    request_timeout_seconds: float


def load_ui_settings() -> UiSettings:
    base_url = os.getenv("V2_API_BASE_URL", "http://127.0.0.1:8000").strip()
    if not base_url:
        raise ValueError("V2_API_BASE_URL must not be empty")

    timeout_text = os.getenv("V2_UI_REQUEST_TIMEOUT_SECONDS", "30").strip()
    try:
        timeout_seconds = float(timeout_text)
    except ValueError as exc:
        raise ValueError("V2_UI_REQUEST_TIMEOUT_SECONDS must be numeric") from exc

    if timeout_seconds <= 0:
        raise ValueError("V2_UI_REQUEST_TIMEOUT_SECONDS must be > 0")

    return UiSettings(
        api_base_url=base_url.rstrip("/"),
        request_timeout_seconds=timeout_seconds,
    )