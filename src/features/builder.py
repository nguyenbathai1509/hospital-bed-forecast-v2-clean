from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


FEATURE_VALUE_COLUMNS = [
    "department_id",
    "planned_beds",
    "occupied_beds",
    "admissions",
    "discharges",
    "transfer_in",
    "transfer_out",
    "net_flow",
    "occupied_beds_lag_1",
    "occupied_beds_lag_2",
    "occupied_beds_lag_3",
    "occupied_beds_mean_3",
    "occupied_beds_std_3",
    "admissions_lag_1",
    "admissions_lag_2",
    "admissions_lag_3",
    "admissions_mean_3",
    "discharges_lag_1",
    "discharges_lag_2",
    "discharges_lag_3",
    "discharges_mean_3",
    "net_flow_lag_1",
    "net_flow_lag_2",
    "net_flow_lag_3",
    "net_flow_mean_3",
    "is_weekend",
    "dow_sin",
    "dow_cos",
]


def _python_scalar(value):
    if value is None:
        return None

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.date()

    return value


def build_features(
    clean_rows: Iterable[dict],
    feature_version: str,
) -> list[dict]:
    rows = list(clean_rows)

    if not rows:
        return []

    df = pd.DataFrame(rows).copy()

    required = {
        "business_date",
        "department_id",
        "planned_beds",
        "occupied_beds",
        "admissions",
        "discharges",
        "transfer_in",
        "transfer_out",
        "source_revision_no",
    }

    missing = sorted(required - set(df.columns))

    if missing:
        raise ValueError(
            f"Cannot build V2 features; missing CLEAN columns: {missing}"
        )

    df["business_date"] = pd.to_datetime(
        df["business_date"],
        errors="raise",
    )

    df = (
        df.sort_values(
            ["department_id", "business_date"],
            kind="stable",
        )
        .reset_index(drop=True)
    )

    # Net Flow = nhập + chuyển đến - ra viện - chuyển đi.
    df["net_flow"] = (
        df["admissions"]
        + df["transfer_in"]
        - df["discharges"]
        - df["transfer_out"]
    )

    # Tất cả lag phải được tính riêng trong từng khoa.
    grouped = df.groupby(
        "department_id",
        sort=False,
        group_keys=False,
    )

    for lag in (1, 2, 3):
        df[f"occupied_beds_lag_{lag}"] = (
            grouped["occupied_beds"].shift(lag)
        )

        df[f"admissions_lag_{lag}"] = (
            grouped["admissions"].shift(lag)
        )

        df[f"discharges_lag_{lag}"] = (
            grouped["discharges"].shift(lag)
        )

        df[f"net_flow_lag_{lag}"] = (
            grouped["net_flow"].shift(lag)
        )

    # Rolling window V2 bao gồm ngày origin t.
    # Với window = 3:
    # [x(t-2), x(t-1), x(t)]
    #
    # occupied_beds_std_3 dùng population standard deviation:
    # ddof = 0.
    for col in (
        "occupied_beds",
        "admissions",
        "discharges",
        "net_flow",
    ):
        rolling = grouped[col].rolling(
            window=3,
            min_periods=3,
        )

        mean_values = (
            rolling.mean()
            .reset_index(level=0, drop=True)
            .sort_index()
        )

        df[f"{col}_mean_3"] = mean_values

        if col == "occupied_beds":
            std_values = (
                rolling.std(ddof=0)
                .reset_index(level=0, drop=True)
                .sort_index()
            )

            df["occupied_beds_std_3"] = std_values

    # Calendar features.
    # pandas:
    # Monday = 0
    # ...
    # Sunday = 6
    dow = df["business_date"].dt.dayofweek

    df["is_weekend"] = (dow >= 5).astype(int)

    df["dow_sin"] = np.sin(
        2.0 * np.pi * dow / 7.0
    )

    df["dow_cos"] = np.cos(
        2.0 * np.pi * dow / 7.0
    )

    out: list[dict] = []

    for rec in df.to_dict(orient="records"):
        row = {
            "origin_date": rec["business_date"].date(),
            "department_id": int(rec["department_id"]),
            "feature_version": feature_version,
            "source_revision_no": int(
                rec["source_revision_no"]
            ),
        }

        for col in FEATURE_VALUE_COLUMNS:
            row[col] = _python_scalar(rec[col])

        out.append(row)

    return out