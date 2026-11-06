from datetime import date

import pytest

import src.monitoring.service as monitoring_service


PIPELINE_ID = "DAY_RECOVERY_GUARD"
BUSINESS_DATE = date(2026, 6, 30)


class _Result:
    def __init__(
        self,
        row,
    ):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Connection:
    def __init__(
        self,
        status,
    ):
        self.status = status

    def execute(
        self,
        statement,
        params=None,
    ):
        sql = " ".join(
            str(statement).split()
        )

        assert (
            "FROM dbo.pipeline_runs"
            in sql
        )

        assert (
            "WHERE run_id=:run_id"
            in sql
        )

        assert (
            params["run_id"]
            == PIPELINE_ID
        )

        return _Result(
            {
                "run_id": PIPELINE_ID,
                "business_date": (
                    BUSINESS_DATE
                ),
                "status": self.status,
            }
        )


class _Context:
    def __init__(
        self,
        status,
    ):
        self.status = status

    def __enter__(self):
        return _Connection(
            self.status
        )

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class _Engine:
    def __init__(
        self,
        status,
    ):
        self.status = status

    def connect(self):
        return _Context(
            self.status
        )


def _patch_cycle(
    monkeypatch,
    *,
    status,
    calls,
):
    monkeypatch.setattr(
        monitoring_service,
        "create_sql_engine",
        lambda: _Engine(status),
    )

    def fake_matching():
        calls.append(
            "ACTUAL_MATCHING"
        )

        return {
            "status":
                "WAITING_FOR_ACTUAL"
        }

    def fake_monitoring(
        *,
        pipeline_run_id,
        business_date,
    ):
        calls.append(
            (
                "MONITORING",
                pipeline_run_id,
                business_date,
            )
        )

        return {
            "status":
                "WAITING_FOR_ACTUAL",
            "pipeline_run_id":
                pipeline_run_id,
            "business_date":
                str(business_date),
        }

    monkeypatch.setattr(
        monitoring_service,
        "run_actual_matching",
        fake_matching,
    )

    monkeypatch.setattr(
        monitoring_service,
        "run_production_monitoring",
        fake_monitoring,
    )


def test_failed_pipeline_is_rejected_before_monitoring(
    monkeypatch,
):
    calls = []

    _patch_cycle(
        monkeypatch,
        status="FAILED",
        calls=calls,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "requires a DATA_READY "
            "pipeline run"
        ),
    ):
        monitoring_service.run_monitoring_cycle(
            pipeline_run_id=PIPELINE_ID
        )

    assert calls == []


def test_data_ready_pipeline_still_runs_monitoring(
    monkeypatch,
):
    calls = []

    _patch_cycle(
        monkeypatch,
        status="DATA_READY",
        calls=calls,
    )

    result = (
        monitoring_service
        .run_monitoring_cycle(
            pipeline_run_id=(
                PIPELINE_ID
            )
        )
    )

    assert (
        result["status"]
        == "WAITING_FOR_ACTUAL"
    )

    assert calls == [
        "ACTUAL_MATCHING",
        (
            "MONITORING",
            PIPELINE_ID,
            BUSINESS_DATE,
        ),
    ]
