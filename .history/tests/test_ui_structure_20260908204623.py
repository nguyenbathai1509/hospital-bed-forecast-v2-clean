from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def test_streamlit_has_all_master_v2_menu_pages():
    dashboard = (APP / "dashboard.py").read_text(encoding="utf-8")
    for label in (
        "🏠 Tổng quan",
        "📂 Dữ liệu",
        "🔮 Dự báo",
        "🧠 Huấn luyện",
        "📊 Kết quả Training",
        "🏆 Model Registry",
        "📈 Monitoring",
    ):
        assert label in dashboard


def test_streamlit_page_files_exist():
    for name in (
        "overview.py",
        "data.py",
        "forecast.py",
        "training.py",
        "training_results.py",
        "models.py",
        "monitoring.py",
    ):
        assert (APP / "pages" / name).is_file()


def test_ui_does_not_import_sql_or_backend_business_services():
    forbidden = (
        "sqlalchemy",
        "pymssql",
        "src.db",
        "src.training",
        "src.forecast",
        "src.promotion",
        "src.monitoring",
    )
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} must not import/use {token}"


def test_ui_requirements_are_isolated():
    text = (ROOT / "requirements-ui.txt").read_text(encoding="utf-8")
    assert "-r requirements-api.txt" in text
    assert "streamlit==" in text


def test_training_results_contains_all_five_training_visualizations():
    text = (APP / "pages" / "training_results.py").read_text(encoding="utf-8")
    for label in (
        "So sánh metric giữa các model",
        "Train / Validation / Test Timeline",
        "Actual vs Predicted – Test Set",
        "Residual over Time",
        "Ranking",
    ):
        assert label in text