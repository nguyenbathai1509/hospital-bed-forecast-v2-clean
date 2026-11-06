from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.forecast.uncertainty import build_uncertainty, business_day_end
from src.forecast import uncertainty_service as service
from src.api.app import create_app
from src.api.dependencies import get_uncertainty_service


ORIGIN = date(2026, 8, 31)
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
REQUEST = dict(candidate_id="RF_TEST", department_id=343, horizon=1,
               origin_date=ORIGIN, prediction_raw=50.0)


def history(n=30, horizon=1):
    result = []
    for i in range(n):
        target = ORIGIN - timedelta(days=n - i - 1)
        origin = target - timedelta(days=horizon)
        result.append(dict(
            official_id=f"OFF_{i}", candidate_id="RF_TEST", department_id=343, horizon=horizon,
            target_date=target, origin_date=origin, prediction_raw=10.0,
            actual_occupied_beds=10 + i, actual_quality_flag="PASS",
            issued_at=datetime.combine(origin, datetime.min.time()) + timedelta(hours=9),
            last_refreshed_at=datetime.combine(target, datetime.min.time()) + timedelta(hours=10),
            match_revision_no=1, actual_source_revision_no=1,
        ))
    return result


def calculate(rows=None, **kwargs):
    arguments = dict(REQUEST, training_data_end=date(2026, 6, 30), now=NOW,
                     rows=history() if rows is None else rows)
    arguments.update(kwargs)
    return build_uncertainty(**arguments)


@pytest.mark.parametrize("horizon", [1, 3])
def test_empirical_order_statistic_and_integer_bounds(horizon):
    rows = history(horizon=horizon)
    before = deepcopy(rows)
    result = calculate(rows, horizon=horizon)
    assert result["status"] == "AVAILABLE"
    assert result["radius"] == 27  # ceil(31*.9) = 28th ordered error, 0-based value 27.
    assert (result["lower_beds"], result["upper_beds"]) == (23, 77)
    assert result["coverage_guaranteed"] is False and result["persisted"] is False
    assert rows == before
    assert len(result["evidence_sha256"]) == 64


@pytest.mark.parametrize("n", [0, 1, 29])
def test_missing_history_never_fabricates_interval(n):
    result = calculate(history(n))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["sample_count"] == n
    assert result["radius"] is None and result["lower_beds"] is None and result["upper_beds"] is None


@pytest.mark.parametrize("change", [
    {"candidate_id": "OTHER"}, {"department_id": 344}, {"horizon": 3},
    {"actual_quality_flag": "CHECK"}, {"last_refreshed_at": NOW},
    {"issued_at": NOW}, {"target_date": date(2026, 5, 1)},
])
def test_incompatible_late_revised_and_stale_rows_are_excluded(change):
    rows = history()
    rows[0].update(change)
    result = calculate(rows)
    assert result["sample_count"] == 29
    assert result["status"] == "INSUFFICIENT_DATA"


def test_future_actual_never_changes_interval_or_evidence():
    rows = history()
    future = dict(rows[-1], official_id="FUTURE", target_date=ORIGIN + timedelta(days=1),
                  origin_date=ORIGIN, actual_occupied_beds=999999)
    assert calculate(rows + [future]) == calculate(rows)


def test_historical_issue_timestamp_excludes_later_matches():
    result = calculate(forecast_created_at=datetime(2026, 8, 31, 9))
    assert result["sample_count"] == 29  # Last target became known at 10 UTC, after issuance.
    assert result["as_of"] == datetime(2026, 8, 31, 9, tzinfo=timezone.utc)


def test_origin_cutoff_uses_vietnam_day_not_utc_midnight():
    assert business_day_end(ORIGIN) == datetime(2026, 8, 31, 17, tzinfo=timezone.utc)
    rows = history()
    rows[-1]["last_refreshed_at"] = datetime(2026, 8, 31, 18)
    assert calculate(rows)["sample_count"] == 29


def test_training_overlap_is_not_used_for_calibration():
    assert calculate(training_data_end=ORIGIN)["sample_count"] == 0
    assert calculate(training_data_end=ORIGIN + timedelta(days=1))["status"] == "INSUFFICIENT_DATA"


def test_future_origin_is_rejected():
    with pytest.raises(ValueError, match="tương lai"):
        calculate(origin_date=date(9999, 12, 31))


def test_calibration_uses_same_nonnegative_center_as_output_band():
    rows = history()
    for row in rows:
        row.update(prediction_raw=-10.0, actual_occupied_beds=3)
    result = calculate(rows, prediction_raw=-5)
    assert result["radius"] == 3
    assert (result["lower_beds"], result["upper_beds"]) == (0, 3)


def test_zero_radius_requires_real_sufficient_history():
    rows = history()
    for row in rows:
        row["actual_occupied_beds"] = 10
    assert calculate(rows)["radius"] == 0
    assert calculate(rows[:29])["radius"] is None


def test_bad_target_offset_is_rejected():
    rows = history()
    rows[0]["origin_date"] -= timedelta(days=1)
    with pytest.raises(ValueError, match="origin/target"):
        calculate(rows)


def test_nonnegative_center_and_outward_rounding_do_not_cap_capacity():
    result = calculate(prediction_raw=-10)
    assert result["prediction_raw"] == -10  # Original point remains untouched.
    assert (result["lower_beds"], result["upper_beds"]) == (0, 27)
    result = calculate(prediction_raw=100.2)
    assert (result["lower_beds"], result["upper_beds"]) == (73, 128)


@pytest.mark.parametrize("field,value", [("actual_occupied_beds", -1), ("actual_occupied_beds", float("inf")),
                                         ("prediction_raw", float("nan"))])
def test_invalid_calibration_fails_explicitly(field, value):
    rows = history()
    rows[0][field] = value
    with pytest.raises(ValueError, match="Invalid calibration values"):
        calculate(rows)


def test_duplicates_are_not_counted_as_extra_evidence():
    rows = history()
    with pytest.raises(ValueError, match="Duplicate"):
        calculate(rows + [dict(rows[0], official_id="DUP")])


def test_read_service_uses_only_read_connection_and_disposes_engine(monkeypatch):
    disposed = []

    class Engine:
        @contextmanager
        def connect(self):
            yield object()
        def dispose(self):
            disposed.append(True)

    repo = SimpleNamespace(candidate=lambda cid: {"horizon": 1, "data_end": date(2026, 6, 30)},
                           calibration_rows=lambda **kw: history())
    monkeypatch.setattr(service, "create_sql_engine", Engine)
    monkeypatch.setattr(service, "UncertaintyRepository", lambda conn: repo)
    result = service.UncertaintyService().calculate(**REQUEST)
    assert result["status"] == "AVAILABLE"
    assert disposed == [True]


def test_repository_scopes_history_to_candidate_department_horizon_and_dates():
    calls = []
    class Connection:
        def execute(self, statement, params):
            calls.append((str(statement), params))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
    service.UncertaintyRepository(Connection()).calibration_rows(**{k: REQUEST[k] for k in
        ("candidate_id", "department_id", "horizon", "origin_date")})
    sql, params = calls[0]
    assert sql.strip().startswith("SELECT")
    assert "official_actual_matches" in sql and "model_evaluation_predictions" not in sql
    for key in ("candidate_id", "department_id", "horizon", "origin_date"):
        assert params[key] == REQUEST[key]
    assert params["start_date"] == ORIGIN - timedelta(days=89)


def api_client():
    app = create_app()
    class Service:
        def calculate(self, **request):
            return calculate(**request)
    app.dependency_overrides[get_uncertainty_service] = Service
    return TestClient(app)


def test_api_returns_read_only_interval_contract():
    response = api_client().post("/forecasts/uncertainty", json={**REQUEST, "origin_date": str(ORIGIN)})
    assert response.status_code == 200
    assert response.json()["upper_beds"] == 77
    assert response.json()["persisted"] is False


@pytest.mark.parametrize("change", [{"horizon": 2}, {"prediction_raw": "NaN"}, {"department_id": 0}, {"unexpected": 1}])
def test_api_rejects_invalid_input(change):
    response = api_client().post("/forecasts/uncertainty", json={**REQUEST, "origin_date": str(ORIGIN), **change})
    assert response.status_code == 422
