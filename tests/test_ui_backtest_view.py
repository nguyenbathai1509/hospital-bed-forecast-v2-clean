from streamlit.testing.v1 import AppTest


def render(recommendations):
    app = AppTest.from_string('''
import streamlit as st
from app.backtest_view import render_comparison
render_comparison(st.session_state["recommendations"], 1)
''')
    app.session_state["recommendations"] = recommendations
    return app.run()


def test_old_recommendation_has_no_fabricated_backtest():
    app = render([{"horizon": 1, "policy": {}}])
    assert not app.exception
    assert not app.dataframe
    assert "lịch sử" in app.caption[0].value


def test_insufficient_data_is_visible_as_warning():
    app = render([{"horizon": 1, "policy": {"comparison": {
        "status": "INSUFFICIENT_DATA", "reason": "Chưa đủ ngày mới",
    }}}])
    assert not app.exception
    assert app.warning[0].value == "Chưa đủ ngày mới"
    assert not app.dataframe


def test_completed_comparison_separates_selection_and_audit():
    app = render([{"horizon": 1, "policy": {"comparison": {
        "status": "COMPLETED", "champion_id": "OLD",
        "folds": [{"start": "2026-07-26", "end": "2026-08-24"}],
        "audit": {"start": "2026-08-25", "end": "2026-08-31"},
        "selection_metrics": [{"candidate_id": "NEW", "mae": .5}],
        "fold_metrics": [{"candidate_id": "NEW", "fold": 1, "mae": .5}],
        "audit_metrics": [{"candidate_id": "NEW", "mae": 10}],
    }}}])
    assert not app.exception
    assert len(app.dataframe) == 3
    assert app.dataframe[0].value["MAE"].iloc[0] == .5
    assert app.dataframe[2].value["MAE"].iloc[0] == 10
    assert not app.button  # Viewing stored reports must not launch training.


def test_baseline_table_compares_saved_metrics_without_changing_recommendation():
    evidence = {
        "status": "COMPLETED", "champion_id": "OLD",
        "selection_metrics": [{"candidate_id": "NEW", "mae": 2, "rmse": 3, "bias": 1}],
        "baseline_benchmarks": {"status": "COMPLETED", "selection_metrics": [
            {"baseline_name": name, "mae": 1, "rmse": 2, "bias": 0}
            for name in ("LAST_VALUE", "SEASONAL_NAIVE_7", "MOVING_AVERAGE_7")], "fold_metrics": []},
    }
    app = render([{"horizon": 1, "policy": {"comparison": evidence}}])
    assert not app.exception and not app.button
    table = app.dataframe[-1].value
    assert len(table) == 4
    assert "Trung bình 7 ngày gần nhất" in table["Mô hình / phương pháp"].tolist()
    assert table["MAE"].tolist() == [2, 1, 1, 1]


def test_missing_baseline_history_is_explicit():
    app = render([{"horizon": 1, "policy": {"comparison": {
        "status": "COMPLETED", "baseline_benchmarks": {"status": "INSUFFICIENT_DATA", "reason": "Thiếu ngày"},
    }}}])
    assert not app.exception
    assert "Chưa đủ dữ liệu" in app.warning[0].value
