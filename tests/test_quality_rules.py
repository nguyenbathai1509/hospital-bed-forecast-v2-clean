from datetime import date
from src.quality.rules import validate_rows, severity_counts


def base_row(d=date(2026,1,1), dep=343, start=54, adm=4, tin=3, dis=4, tout=7, end=50):
    return {
        "business_date": d,
        "source_weekday": "T4",
        "source_month": 1,
        "department_id": dep,
        "department_code": "K481",
        "department_name": "Khoa Hồi Sức Tích Cực",
        "planned_beds": 55,
        "occupied_start": start,
        "admissions": adm,
        "transfer_in": tin,
        "discharges": dis,
        "transfer_out": tout,
        "occupied_end": end,
        "occupied_beds": end,
        "balance_status": "OK",
        "occupancy_rate": end/55*100,
    }


def test_clean_row_has_no_issue():
    issues = validate_rows([base_row()])
    assert severity_counts(issues) == {"ERROR":0,"WARNING":0,"CHECK":0}


def test_known_balance_check_is_check_not_error():
    row = base_row(date(2026,3,20), start=52, adm=16, tin=1, dis=11, tout=4, end=53)
    row["source_weekday"] = "T5"
    row["source_month"] = 3
    row["balance_status"] = "KIEM TRA"
    row["occupancy_rate"] = 53/55*100
    issues = validate_rows([row])
    assert any(i.rule_id == "DQ07" and i.severity == "CHECK" and i.difference_value == -1 for i in issues)
    assert not any(i.severity == "ERROR" for i in issues)


def test_duplicate_business_key_is_error():
    row = base_row()
    issues = validate_rows([row, dict(row)])
    assert any(i.rule_id == "DQ03" and i.severity == "ERROR" for i in issues)


def test_dq09_accepts_sql_decimal_6_rounding():
    # 48/55*100 = 87.2727272727...
    # SQL DECIMAL(12,6) stores 87.272727.
    # Difference ~= 2.73e-7 percentage points.
    # It must not become a false DQ09 WARNING.
    row = base_row(
        start=52,
        adm=4,
        tin=3,
        dis=4,
        tout=7,
        end=48,
    )

    row["occupancy_rate"] = round(
        row["occupancy_rate"],
        6,
    )

    issues = validate_rows([row])

    assert not any(
        issue.rule_id == "DQ09"
        for issue in issues
    )
