from __future__ import annotations

from copy import deepcopy

import pytest

from src.demo_reset.service import (
    DEMO_RESET_CONFIRMATION,
    RESET_DELETE_ORDER,
    DemoResetBusyError,
    DemoResetConfirmationError,
    DemoResetDisabledError,
    DemoResetService,
)


class FakeResult:
    def __init__(self, value: int):
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeConnection:
    def __init__(
        self,
        *,
        counts: dict[str, int],
        retained: dict[str, int] | None = None,
        busy: dict[str, int] | None = None,
        fail_on_delete: str | None = None,
    ) -> None:
        self.counts = dict(counts)
        self.retained = dict(
            retained
            or {
                "departments": 2,
                "schema_migrations": 9,
            }
        )
        self.busy = {
            "pipeline_runs": 0,
            "api_training_jobs": 0,
            "training_runs": 0,
            "production_monitoring_runs": 0,
            **(busy or {}),
        }
        self.fail_on_delete = fail_on_delete
        self.deleted_order: list[str] = []

    @staticmethod
    def _normalized(statement) -> str:
        return " ".join(str(statement).lower().split())

    @staticmethod
    def _table_after(normalized: str, marker: str) -> str:
        value = normalized.split(marker, 1)[1]
        return value.split()[0].strip()

    def execute(self, statement):
        sql = self._normalized(statement)

        if sql.startswith("delete from dbo."):
            table = self._table_after(sql, "delete from dbo.")

            if table == self.fail_on_delete:
                raise RuntimeError(
                    f"Injected delete failure for dbo.{table}"
                )

            self.deleted_order.append(table)
            self.counts[table] = 0
            return FakeResult(0)

        if "select count(*) from dbo.departments" in sql:
            return FakeResult(self.retained["departments"])

        if "select count(*) from dbo.schema_migrations" in sql:
            return FakeResult(self.retained["schema_migrations"])

        if "select count(*) from dbo." in sql:
            table = self._table_after(
                sql,
                "select count(*) from dbo.",
            )

            # Query có WHERE status là busy guard.
            if " where status " in f" {sql} ":
                return FakeResult(self.busy.get(table, 0))

            return FakeResult(self.counts.get(table, 0))

        raise AssertionError(f"Unexpected SQL: {sql}")


class ConnectContext:
    def __init__(self, connection: FakeConnection):
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class BeginContext:
    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self._counts_before: dict[str, int] | None = None
        self._retained_before: dict[str, int] | None = None
        self._deleted_before: list[str] | None = None

    def __enter__(self) -> FakeConnection:
        self._counts_before = deepcopy(self.connection.counts)
        self._retained_before = deepcopy(self.connection.retained)
        self._deleted_before = list(self.connection.deleted_order)
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            assert self._counts_before is not None
            assert self._retained_before is not None
            assert self._deleted_before is not None

            # Mô phỏng transaction rollback.
            self.connection.counts = self._counts_before
            self.connection.retained = self._retained_before
            self.connection.deleted_order = self._deleted_before

        return False


class FakeEngine:
    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self.connect_calls = 0
        self.begin_calls = 0

    def connect(self) -> ConnectContext:
        self.connect_calls += 1
        return ConnectContext(self.connection)

    def begin(self) -> BeginContext:
        self.begin_calls += 1
        return BeginContext(self.connection)


def make_counts(value: int = 1) -> dict[str, int]:
    return {
        table_name: value
        for table_name in RESET_DELETE_ORDER
    }


def test_status_is_read_only(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "false")

    counts = make_counts(0)
    counts["pipeline_runs"] = 10
    counts["raw_bed_daily"] = 362
    counts["model_candidates"] = 8

    connection = FakeConnection(counts=counts)
    engine = FakeEngine(connection)

    result = DemoResetService(engine=engine).status()

    assert result["enabled"] is False
    assert result["clean"] is False
    assert result["busy"] is False

    assert result["counts"]["pipeline_runs"] == 10
    assert result["counts"]["raw_bed_daily"] == 362
    assert result["counts"]["model_candidates"] == 8

    assert result["retained"] == {
        "departments": 2,
        "schema_migrations": 9,
    }

    assert connection.deleted_order == []
    assert engine.begin_calls == 0


def test_disabled_guard_blocks_before_transaction(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "false")

    connection = FakeConnection(counts=make_counts())
    engine = FakeEngine(connection)

    with pytest.raises(DemoResetDisabledError):
        DemoResetService(engine=engine).reset(
            confirmation=DEMO_RESET_CONFIRMATION
        )

    assert engine.begin_calls == 0
    assert connection.deleted_order == []


def test_wrong_confirmation_blocks_before_transaction(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "true")

    connection = FakeConnection(counts=make_counts())
    engine = FakeEngine(connection)

    with pytest.raises(DemoResetConfirmationError):
        DemoResetService(engine=engine).reset(
            confirmation="SAI CUM XAC NHAN"
        )

    assert engine.begin_calls == 0
    assert connection.deleted_order == []


def test_busy_guard_blocks_reset(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "true")

    original_counts = make_counts()

    connection = FakeConnection(
        counts=original_counts,
        busy={
            "api_training_jobs": 1,
        },
    )
    engine = FakeEngine(connection)

    with pytest.raises(DemoResetBusyError):
        DemoResetService(engine=engine).reset(
            confirmation=DEMO_RESET_CONFIRMATION
        )

    assert engine.begin_calls == 1
    assert connection.counts == original_counts
    assert connection.deleted_order == []


def test_successful_reset_uses_exact_fk_safe_order(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "true")

    connection = FakeConnection(
        counts=make_counts(),
        retained={
            "departments": 2,
            "schema_migrations": 9,
        },
    )
    engine = FakeEngine(connection)

    result = DemoResetService(engine=engine).reset(
        confirmation=DEMO_RESET_CONFIRMATION
    )

    assert result["status"] == "RESET_COMPLETED"
    assert result["clean"] is True

    assert tuple(connection.deleted_order) == RESET_DELETE_ORDER
    assert all(value == 0 for value in connection.counts.values())

    assert result["retained"] == {
        "departments": 2,
        "schema_migrations": 9,
    }


def test_transaction_rolls_back_when_delete_fails(monkeypatch) -> None:
    monkeypatch.setenv("V2_DEMO_RESET_ENABLED", "true")

    original_counts = make_counts()

    connection = FakeConnection(
        counts=original_counts,
        fail_on_delete="model_candidates",
    )
    engine = FakeEngine(connection)

    with pytest.raises(
        RuntimeError,
        match="Injected delete failure",
    ):
        DemoResetService(engine=engine).reset(
            confirmation=DEMO_RESET_CONFIRMATION
        )

    # Fake transaction phải phục hồi toàn bộ trạng thái.
    assert connection.counts == original_counts
    assert connection.deleted_order == []
