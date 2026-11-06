from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st


def apply_global_styles() -> None:
    """Read on rerun so CSS edits appear without restarting the Python worker."""
    css = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def sidebar_brand(title: str, subtitle: str) -> None:
    st.markdown(
        '<div class="hb-brand">'
        '<div class="hb-brand__icon" aria-hidden="true">✚</div>'
        f'<div class="hb-brand__title">{escape(title)}</div>'
        f'<div class="hb-brand__subtitle">{escape(subtitle)}</div>'
        '</div>', unsafe_allow_html=True,
    )


def sidebar_meta(label: str, value: str) -> None:
    st.markdown(
        '<div class="hb-sidebar-meta">'
        f'<div class="hb-sidebar-meta__label">{escape(label)}</div>'
        f'<div class="hb-sidebar-meta__value" title="{escape(value)}">{escape(value)}</div>'
        '</div>', unsafe_allow_html=True,
    )


def sidebar_note(text: str) -> None:
    st.markdown(f'<div class="hb-sidebar-note">{escape(text)}</div>', unsafe_allow_html=True)
