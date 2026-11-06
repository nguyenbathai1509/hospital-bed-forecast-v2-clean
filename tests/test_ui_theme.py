from pathlib import Path
import re
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/theme.css").read_text(encoding="utf-8")


def contrast(fg, bg):
    def luminance(value):
        c = [int(value[i:i+2], 16)/255 for i in (1,3,5)]
        c = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in c]
        return sum(v*w for v,w in zip(c, (.2126,.7152,.0722)))
    a,b = sorted([luminance(fg),luminance(bg)])
    return (b+.05)/(a+.05)


@pytest.mark.parametrize("fg,bg", [
    ("#ffffff","#087e78"), ("#ffffff","#06655f"),
    ("#526577","#e7edf2"), ("#526577","#f3f6fa"),
    ("#edf5fb","#102c3d"), ("#c3d4df","#102c3d"),
    ("#edf5fb","#1d4053"), ("#23465c","#ffffff"),
])
def test_design_text_pairs_exceed_minimum_contrast(fg, bg):
    assert fg in CSS and bg in CSS
    assert contrast(fg,bg) >= 4.5


def test_css_has_no_global_text_or_generated_class_overrides():
    assert not re.search(r"(?:^|[{}])\s*(?:p|label|span|code|a|h2|h3)(?:\s|,|\{)", CSS)
    assert "st-emotion-cache-" not in CSS
    assert 'label > div:first-child' not in CSS
    assert 'class*="css"' not in CSS
    assert "prefers-reduced-motion" in CSS and "focus-visible" in CSS
    assert "color: inherit !important" in CSS


def test_native_theme_matches_shared_tokens_and_sidebar():
    theme = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))["theme"]
    assert theme["primaryColor"].lower() == "#087e78"
    assert contrast(theme["textColor"], theme["backgroundColor"]) >= 4.5
    assert contrast(theme["sidebar"]["textColor"], theme["sidebar"]["backgroundColor"]) >= 4.5


def test_gallery_renders_all_control_types_without_backend():
    app = AppTest.from_file(str(ROOT / "tests/fixtures/ui_gallery.py")).run()
    assert not app.exception
    assert len(app.metric) == 4
    assert len(app.dataframe) == 1
    assert any(b.disabled for b in app.button)
    assert len(app.sidebar.radio) == 1
