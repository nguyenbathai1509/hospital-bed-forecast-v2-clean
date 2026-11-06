from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from collections import defaultdict
import math
from typing import Iterable

from src.contracts import REQUIRED_NORMALIZED


@dataclass(frozen=True)
class QualityIssue:
    rule_id: str
    severity: str
    message: str
    business_date: date | None = None
    department_id: int | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    difference_value: float | None = None


_VI_WEEKDAY = {0: "T1", 1: "T2", 2: "T3", 3: "T4", 4: "T5", 5: "T6", 6: "CN"}

# raw_bed_daily.occupancy_rate is stored as SQL DECIMAL(12,6).
# Half of one unit at 6 decimal places is 0.5e-6 = 5e-7.
# Differences within this tolerance are SQL quantization, not DQ errors.
OCCUPANCY_RATE_SQL_ABS_TOL = 5e-7


def _issue(rule: str, severity: str, msg: str, row: dict | None = None, **kwargs) -> QualityIssue:
    return QualityIssue(
        rule_id=rule,
        severity=severity,
        message=msg,
        business_date=(row or {}).get("business_date"),
        department_id=(row or {}).get("department_id"),
        **kwargs,
    )


def validate_rows(rows: Iterable[dict], schema_passed: bool = True) -> list[QualityIssue]:
    rows = list(rows)
    issues: list[QualityIssue] = []
    if not schema_passed:
        return [_issue("DQ01", "ERROR", "Schema does not match the 16-column V2 source contract.")]

    # DQ02 required values.
    for r in rows:
        for field in REQUIRED_NORMALIZED:
            if r.get(field) is None or (isinstance(r.get(field), str) and not r.get(field).strip()):
                issues.append(_issue("DQ02", "ERROR", f"Required field {field} is missing.", r, field_name=field))

    # DQ03 unique business key within source batch.
    seen: set[tuple] = set()
    for r in rows:
        key = (r.get("business_date"), r.get("department_id"))
        if key in seen:
            issues.append(_issue("DQ03", "ERROR", "Duplicate business_date + department_id in source batch.", r))
        seen.add(key)

    grouped: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("department_id") is not None:
            grouped[int(r["department_id"])].append(r)

    # DQ04 parse/continuity by department.
    for dep, group in grouped.items():
        dates = sorted(r["business_date"] for r in group if r.get("business_date") is not None)
        for prev, cur in zip(dates, dates[1:]):
            if cur != prev + timedelta(days=1):
                issues.append(QualityIssue(
                    "DQ04", "ERROR", f"Date gap for department {dep}: {prev} -> {cur}.",
                    business_date=cur, department_id=dep,
                    expected_value=str(prev + timedelta(days=1)), actual_value=str(cur),
                ))

    # DQ05 non-negative counts; planned_beds must be > 0.
    non_negative = ["occupied_start", "admissions", "transfer_in", "discharges", "transfer_out", "occupied_end", "occupied_beds"]
    for r in rows:
        if r.get("planned_beds") is not None and r["planned_beds"] <= 0:
            issues.append(_issue("DQ05", "ERROR", "planned_beds must be > 0.", r, field_name="planned_beds", actual_value=str(r["planned_beds"])))
        for field in non_negative:
            value = r.get(field)
            if value is not None and value < 0:
                issues.append(_issue("DQ05", "ERROR", f"{field} must be >= 0.", r, field_name=field, actual_value=str(value)))

    # DQ06 department metadata consistency.
    dep_meta: dict[int, tuple[str, str]] = {}
    for r in rows:
        dep = r.get("department_id")
        if dep is None:
            continue
        meta = (str(r.get("department_code")), str(r.get("department_name")))
        if dep in dep_meta and dep_meta[dep] != meta:
            issues.append(_issue("DQ06", "ERROR", "department_id maps to inconsistent code/name.", r, actual_value=str(meta), expected_value=str(dep_meta[dep])))
        dep_meta.setdefault(dep, meta)

    # Row-level derived checks DQ07-DQ10/DQ12.
    for r in rows:
        required_math = [r.get(k) for k in ["occupied_start", "admissions", "transfer_in", "discharges", "transfer_out", "occupied_end", "occupied_beds", "planned_beds"]]
        if any(v is None for v in required_math):
            continue
        expected_end = r["occupied_start"] + r["admissions"] + r["transfer_in"] - r["discharges"] - r["transfer_out"]
        balance_error = r["occupied_end"] - expected_end
        if balance_error != 0:
            issues.append(_issue(
                "DQ07", "CHECK", "Patient balance is not zero; keep source values and audit, do not auto-correct.", r,
                expected_value=str(expected_end), actual_value=str(r["occupied_end"]), difference_value=float(balance_error),
            ))
        consistency_error = r["occupied_end"] - r["occupied_beds"]
        if consistency_error != 0:
            issues.append(_issue(
                "DQ08", "CHECK", "occupied_end differs from occupied_beds.", r,
                expected_value=str(r["occupied_end"]), actual_value=str(r["occupied_beds"]), difference_value=float(consistency_error),
            ))
        expected_rate = r["occupied_beds"] / r["planned_beds"] * 100.0
        actual_rate = r.get("occupancy_rate")
        if actual_rate is None or not math.isclose(
            float(actual_rate),
            expected_rate,
            rel_tol=0.0,
            abs_tol=OCCUPANCY_RATE_SQL_ABS_TOL,
        ):
            issues.append(_issue(
                "DQ09", "WARNING", "Source occupancy_rate differs from occupied_beds/planned_beds*100.", r,
                expected_value=f"{expected_rate:.10f}", actual_value=str(actual_rate),
                difference_value=None if actual_rate is None else float(actual_rate) - expected_rate,
            ))
        expected_weekday = _VI_WEEKDAY[r["business_date"].weekday()]
        if r.get("source_weekday") != expected_weekday or int(r.get("source_month")) != r["business_date"].month:
            issues.append(_issue(
                "DQ10", "WARNING", "Source THU/THANG is inconsistent with NGAY.", r,
                expected_value=f"{expected_weekday}/{r['business_date'].month}",
                actual_value=f"{r.get('source_weekday')}/{r.get('source_month')}",
            ))
        expected_status = "OK" if balance_error == 0 else "KIEM TRA"
        if str(r.get("balance_status", "")).strip().upper() != expected_status:
            issues.append(_issue(
                "DQ12", "CHECK", "Source balance_status is inconsistent with calculated balance_error.", r,
                expected_value=expected_status, actual_value=str(r.get("balance_status")),
            ))

    # DQ11 state continuity: next start == previous end per department.
    for dep, group in grouped.items():
        group = sorted(group, key=lambda r: r["business_date"])
        for prev, cur in zip(group, group[1:]):
            if prev.get("occupied_end") is None or cur.get("occupied_start") is None:
                continue
            if cur["occupied_start"] != prev["occupied_end"]:
                issues.append(_issue(
                    "DQ11", "CHECK", "Next-day occupied_start differs from previous occupied_end.", cur,
                    expected_value=str(prev["occupied_end"]), actual_value=str(cur["occupied_start"]),
                    difference_value=float(cur["occupied_start"] - prev["occupied_end"]),
                ))
    return issues


def has_error(issues: Iterable[QualityIssue]) -> bool:
    return any(i.severity == "ERROR" for i in issues)


def severity_counts(issues: Iterable[QualityIssue]) -> dict[str, int]:
    result = {"ERROR": 0, "WARNING": 0, "CHECK": 0}
    for issue in issues:
        result[issue.severity] = result.get(issue.severity, 0) + 1
    return result
