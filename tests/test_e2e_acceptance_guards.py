from datetime import datetime
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from scripts import run_e2e_acceptance as acceptance


@pytest.mark.parametrize("protected,target", [
    ("HospitalBedForecastV2", "HospitalBedForecastV2"),
    ("hospitalbedforecastv2_e2e", "HospitalBedForecastV2_E2E"),
    ("HospitalBedForecastV2", "master"),
    ("HospitalBedForecastV2", "OtherDatabase"),
])
def test_database_target_guard_rejects_unsafe_names(protected, target):
    with pytest.raises(RuntimeError):
        acceptance.assert_isolated_name(protected, target)


def test_only_explicit_isolated_database_is_allowed():
    acceptance.assert_isolated_name("HospitalBedForecastV2", "HospitalBedForecastV2_E2E")


def test_file_guard_rejects_source_and_evidence_root():
    for path in (acceptance.ROOT, acceptance.ROOT / "data/HSNoi.xlsx", acceptance.EVIDENCE_ROOT,
                 acceptance.EVIDENCE_ROOT / "../outside.xlsx"):
        with pytest.raises(RuntimeError):
            acceptance.sandbox_path(path)


def test_added_days_are_balanced_and_only_update_test_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "EVIDENCE_ROOT", tmp_path)
    project = tmp_path / "run/project"
    (project / "data").mkdir(parents=True)
    for name in acceptance.FILES:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Export Worksheet"
        worksheet.append([f"column_{i}" for i in range(16)])
        worksheet.append([datetime(2026, 6, 30), "T2", 6, 343, "K481", "Test", 55,
                          44, 5, 2, 7, 4, 40, 40, "OK", 40 / 55 * 100])
        workbook.save(project / "data" / name)
    assert acceptance.append_days(project, 3) == "2026-07-03"
    for name in acceptance.FILES:
        workbook = load_workbook(project / "data" / name)
        rows = list(workbook.active.values)
        assert len(rows) == 5
        for previous, row in zip(rows[1:], rows[2:]):
            assert row[7] == previous[12]
            assert row[12] == row[7] + row[8] + row[9] - row[10] - row[11]
            assert row[12] == row[13]
            assert row[15] == pytest.approx(row[13] / row[6] * 100)
        workbook.close()


def test_appending_preserves_excel_cached_formula_values(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "EVIDENCE_ROOT", tmp_path)
    project = tmp_path / "run/project"
    (project / "data").mkdir(parents=True)
    for name in acceptance.FILES:
        path = project / "data" / name
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Export Worksheet"
        worksheet.append([f"column_{i}" for i in range(16)])
        worksheet.append([datetime(2026, 6, 30), "T2", 6, 343, "K481", "Test", 50,
                          40, 0, 0, 0, 0, 40, 40, "OK", "=N2/G2*100"])
        workbook.save(path)
        # Emulate an Excel-saved workbook with a cached value for the formula.
        with ZipFile(path) as archive:
            entries = {entry.filename: archive.read(entry.filename) for entry in archive.infolist()}
        xml = ElementTree.fromstring(entries["xl/worksheets/sheet1.xml"])
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        cell = xml.find(".//s:c[@r='P2']/s:v", ns)
        assert cell is not None
        cell.text = "80"
        entries["xl/worksheets/sheet1.xml"] = ElementTree.tostring(xml)
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            for filename, content in entries.items():
                archive.writestr(filename, content)
        path.write_bytes(buffer.getvalue())
    acceptance.append_days(project, 1)
    for name in acceptance.FILES:
        workbook = load_workbook(project / "data" / name, data_only=True)
        assert workbook.active["P2"].value == 80
        assert workbook.active["P3"].value == 80
        workbook.close()
