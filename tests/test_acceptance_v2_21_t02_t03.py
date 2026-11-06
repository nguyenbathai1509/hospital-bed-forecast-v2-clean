from pathlib import Path
from shutil import copy2

from openpyxl import load_workbook

from src.sources.excel_adapter import ExcelSourceAdapter
import src.services.daily_pipeline_service as dps


def test_t02_missing_source_then_available_is_retryable(
    tmp_path: Path,
):
    temp_noi = tmp_path / "HSNoi.xlsx"
    temp_ngoai = tmp_path / "hsNgoai.xlsx"

    adapter = ExcelSourceAdapter(
        [temp_noi, temp_ngoai]
    )

    # Attempt 1: source chưa tồn tại.
    first = adapter.check_readiness()

    assert not first.ready
    assert first.business_date is None
    assert first.reason == "SOURCE_FILES_MISSING"

    # Source xuất hiện sau đó.
    copy2(
        Path("data/HSNoi.xlsx"),
        temp_noi,
    )
    copy2(
        Path("data/hsNgoai.xlsx"),
        temp_ngoai,
    )

    # Retry trên chính adapter đó.
    second = adapter.check_readiness()

    assert second.ready
    assert str(second.business_date) == "2026-06-30"

    # Retry thêm lần nữa vẫn ổn định.
    third = adapter.check_readiness()

    assert third.ready
    assert third.business_date == second.business_date


class _FakeBegin:
    def __enter__(self):
        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class _FakeEngine:
    def begin(self):
        return _FakeBegin()


class _FakeRepository:
    calls = []

    def __init__(self, conn):
        self.conn = conn

    def create_pipeline_run(
        self,
        **kwargs,
    ):
        self.__class__.calls.append(
            ("create", kwargs)
        )

    def finish_pipeline_run(
        self,
        *args,
        **kwargs,
    ):
        self.__class__.calls.append(
            ("finish", args, kwargs)
        )


def test_t03_missing_required_source_column_fails_before_downstream(
    tmp_path: Path,
    monkeypatch,
):
    temp_noi = tmp_path / "HSNoi.xlsx"
    temp_ngoai = tmp_path / "hsNgoai.xlsx"

    copy2(
        Path("data/HSNoi.xlsx"),
        temp_noi,
    )
    copy2(
        Path("data/hsNgoai.xlsx"),
        temp_ngoai,
    )

    # Chỉ phá schema trên COPY trong tmp_path.
    wb = load_workbook(temp_noi)
    ws = wb["Export Worksheet"]

    assert ws["A1"].value == "NGAY"
    ws["A1"] = "NGAY_BROKEN"

    wb.save(temp_noi)

    adapter = ExcelSourceAdapter(
        [temp_noi, temp_ngoai]
    )

    _FakeRepository.calls = []

    monkeypatch.setattr(
        dps,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )

    monkeypatch.setattr(
        dps,
        "CoreRepository",
        _FakeRepository,
    )

    def forbidden_downstream(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Downstream stage must not run "
            "after source schema failure."
        )

    for name in [
        "build_features",
        "build_ml_samples",
        "activate_due_scheduled_models",
        "run_actual_matching",
        "run_production_monitoring",
    ]:
        monkeypatch.setattr(
            dps,
            name,
            forbidden_downstream,
        )

    result = dps.run_daily_pipeline(
        adapter
    )

    assert result["status"] == "FAILED"

    assert (
        result["readiness"]["reason"]
        == "SOURCE_UNREADABLE_OR_SCHEMA_INVALID"
    )

    assert (
        "DQ01 schema mismatch"
        in result["readiness"]["details"]["error"]
    )

    assert (
        result["stages"]["SOURCE_READINESS"]
        == "FAILED"
    )

    # Không có downstream stage.
    for stage in [
        "EXTRACT_RAW",
        "DATA_QUALITY",
        "CLEAN",
        "FEATURE",
        "ML_SAMPLES",
    ]:
        assert stage not in result["stages"]

    # Chỉ được tạo audit run rồi finish FAILED.
    assert [
        call[0]
        for call in _FakeRepository.calls
    ] == [
        "create",
        "finish",
    ]
