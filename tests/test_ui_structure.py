from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"



def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id

    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = func

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)

        return ".".join(reversed(parts))

    return None


def test_streamlit_has_all_master_v2_menu_pages():
    """Ki?m tra wiring ?i?u h??ng, kh?ng ph? thu?c nh?n hi?n th? ?? d?ch."""
    dashboard_path = APP / "dashboard.py"
    tree = ast.parse(dashboard_path.read_text(encoding="utf-8"))

    pages_dict: ast.Dict | None = None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        if any(
            isinstance(target, ast.Name) and target.id == "PAGES"
            for target in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            pages_dict = node.value
            break

    assert pages_dict is not None, "dashboard.py must define a PAGES mapping"

    render_targets = [
        ast.unparse(value)
        for value in pages_dict.values
    ]

    assert render_targets == [
        "overview.render",
        "data.render",
        "training.render",
        "training_results.render",
        "models.render",
        "forecast.render",
        "monitoring.render",
        "demo_reset.render",
    ]


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


def test_unified_requirements_preserve_all_dependencies():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    entries = [line.strip() for line in text.splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    expected = {
        "SQLAlchemy==2.0.43", "pymssql==2.3.7", "python-dotenv==1.1.1",
        "pandas==2.3.2", "openpyxl==3.1.5", "pytest==8.4.1",
        "fastapi==0.141.1", "uvicorn==0.52.4", "pydantic==2.13.5",
        "httpx==0.28.1", "streamlit==1.49.1", "altair==5.5.0",
        "scikit-learn==1.8.0", "joblib==1.5.3", "xgboost==3.1.3",
        "tensorflow==2.20.0",
    }
    assert set(entries) == expected
    assert len(entries) == len(expected)


def test_training_results_contains_all_five_training_visualizations():
    """Ki?m tra c?u tr?c bi?u ?? thay v? ph? thu?c ti?u ?? hi?n th?."""
    path = APP / "pages" / "training_results.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    call_names = [
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := _call_name(node)) is not None
    ]

    string_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }

    # 1. Bi?u ?? so s?nh metric gi?a c?c m? h?nh
    assert "st.bar_chart" in call_names

    # 2. Timeline Train / Validation / Test
    assert "_timeline_chart" in function_names
    assert "st.altair_chart" in call_names

    # 3 + 4. Actual vs Predicted v? Residual over Time
    assert call_names.count("st.line_chart") >= 2

    # 5. Ranking v?n l?y t? collection rankings v? render dataframe
    assert "rankings" in string_constants
    assert "dataframe" in call_names

