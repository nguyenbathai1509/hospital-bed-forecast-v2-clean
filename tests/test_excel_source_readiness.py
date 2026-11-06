from pathlib import Path

from src.sources.excel_adapter import (
    ExcelSourceAdapter,
)


def test_missing_excel_source_is_waiting(
    tmp_path: Path,
):
    adapter = ExcelSourceAdapter(
        [
            tmp_path / "missing1.xlsx",
            tmp_path / "missing2.xlsx",
        ]
    )

    result = (
        adapter.check_readiness()
    )

    assert not result.ready
    assert (
        result.reason
        == "SOURCE_FILES_MISSING"
    )