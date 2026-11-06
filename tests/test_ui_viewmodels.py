from __future__ import annotations

from app.viewmodels import (
    candidate_rows_for_horizon,
    department_label,
    department_mae_matrix,
    enrich_department_metrics,
    latest_completed_training_run,
    official_index,
    production_by_horizon,
    summarize_dashboard,
)


def test_department_label_is_id_plus_name():
    assert department_label({"department_id": 343, "department_name": "HSTC"}) == "343 - HSTC"


def test_latest_completed_training_run_ignores_failed_and_running():
    rows = [
        {"run_id": "A", "status": "FAILED", "completed_at": "2026-09-08T10:00:00"},
        {"run_id": "B", "status": "COMPLETED", "completed_at": "2026-09-08T09:00:00"},
        {"run_id": "C", "status": "COMPLETED", "completed_at": "2026-09-08T11:00:00"},
    ]
    assert latest_completed_training_run(rows)["run_id"] == "C"


def test_production_by_horizon_maps_h1_h3():
    payload = {"horizons": [{"horizon": 1, "active": {"model_family": "RF"}}, {"horizon": 3, "active": {"model_family": "SVR"}}]}
    result = production_by_horizon(payload)
    assert result[1]["active"]["model_family"] == "RF"
    assert result[3]["active"]["model_family"] == "SVR"


def test_official_index_uses_department_and_horizon_business_key():
    rows = [{"department_id": 343, "horizon": 1, "official_id": "OFF1"}]
    assert official_index(rows)[(343, 1)]["official_id"] == "OFF1"


def test_dashboard_summary_marks_missing_official_as_pending():
    summary = summarize_dashboard(
        data_status={"business_date": "2026-06-30", "status": "DATA_READY"},
        pipeline_runs=[{"run_id": "DAY1", "status": "DATA_READY"}],
        training_runs=[{"run_id": "TRN1", "status": "COMPLETED", "completed_at": "2026-09-08T10:00:00"}],
        production={
            "normal_change_quota_used": True,
            "horizons": [
                {"horizon": 1, "active": {"model_family": "RF"}, "recommendation": {"recommended_family": "RF", "action": "KEEP"}},
                {"horizon": 3, "active": {"model_family": "SVR"}, "recommendation": {"recommended_family": "SVR", "action": "KEEP"}},
            ],
        },
        officials=[{"department_id": 343, "horizon": 1, "prediction_rounded": 47}],
        departments=[{"department_id": 343, "department_name": "HSTC"}],
    )
    states = {(row["department_id"], row["horizon"]): row for row in summary["official_states"]}
    assert states[(343, 1)]["status"] == "OFFICIAL"
    assert states[(343, 3)]["status"] == "PENDING"


def test_dashboard_summary_keeps_recommended_separate_from_production():
    summary = summarize_dashboard(
        data_status={},
        pipeline_runs=[],
        training_runs=[],
        production={
            "normal_change_quota_used": False,
            "horizons": [
                {"horizon": 1, "active": {"model_family": "RF"}, "recommendation": {"recommended_family": "SVR", "action": "PROMOTE"}},
                {"horizon": 3, "active": {"model_family": "SVR"}, "recommendation": {"recommended_family": "SVR", "action": "KEEP"}},
            ],
        },
        officials=[],
        departments=[],
    )
    assert summary["production_h1"]["model_family"] == "RF"
    assert summary["recommendation_h1"]["recommended_family"] == "SVR"


def test_candidate_rows_are_filtered_and_ranked_by_mae():
    rows = [
        {"horizon": 1, "model_family": "RF", "mae": 2.25},
        {"horizon": 1, "model_family": "SVR", "mae": 2.24},
        {"horizon": 3, "model_family": "SVR", "mae": 2.20},
    ]
    result = candidate_rows_for_horizon(rows, 1)
    assert [row["model_family"] for row in result] == ["SVR", "RF"]


def test_department_mae_matrix_pivots_by_family():
    metrics = [
        {"horizon": 1, "department_id": 343, "model_family": "RF", "mae": 2.7},
        {"horizon": 1, "department_id": 343, "model_family": "SVR", "mae": 2.8},
        {"horizon": 1, "department_id": 344, "model_family": "RF", "mae": 1.7},
        {"horizon": 3, "department_id": 343, "model_family": "SVR", "mae": 2.9},
    ]
    result = department_mae_matrix(metrics, 1)
    assert result == [
        {"department_id": 343, "RF": 2.7, "SVR": 2.8},
        {"department_id": 344, "RF": 1.7},
    ]


def test_enrich_department_metrics_joins_candidate_horizon_and_family():
    metrics = [{"candidate_id": "C1", "department_id": 343, "mae": 2.7}]
    candidates = [{"candidate_id": "C1", "horizon": 1, "model_family": "RF"}]
    result = enrich_department_metrics(metrics, candidates)
    assert result[0]["horizon"] == 1
    assert result[0]["model_family"] == "RF"
    assert result[0]["mae"] == 2.7


def test_metric_comparison_rows_supports_global_and_department_scope():
    from app.viewmodels import metric_comparison_rows

    global_rows = [
        {"horizon": 1, "model_family": "RF", "mae": 2.25},
        {"horizon": 1, "model_family": "SVR", "mae": 2.24},
        {"horizon": 3, "model_family": "RF", "mae": 2.46},
    ]
    assert metric_comparison_rows(
        global_rows,
        horizon=1,
        metric_key="mae",
    ) == [
        {"model_family": "RF", "value": 2.25},
        {"model_family": "SVR", "value": 2.24},
    ]

    dept_rows = [
        {"horizon": 1, "department_id": 343, "model_family": "RF", "bias": -0.2},
        {"horizon": 1, "department_id": 344, "model_family": "RF", "bias": -0.4},
    ]
    assert metric_comparison_rows(
        dept_rows,
        horizon=1,
        metric_key="bias",
        department_id=343,
    ) == [{"model_family": "RF", "value": -0.2}]


def test_evaluation_chart_frame_preserves_actual_prediction_and_residual():
    from app.viewmodels import evaluation_chart_frame

    result = evaluation_chart_frame(
        [
            {
                "target_date": "2026-05-25",
                "actual_occupied_beds": 51.0,
                "prediction_raw": 49.8,
                "residual": 1.2,
            }
        ]
    )
    assert result == [
        {
            "target_date": "2026-05-25",
            "actual": 51.0,
            "predicted": 49.8,
            "residual": 1.2,
            "zero": 0.0,
        }
    ]