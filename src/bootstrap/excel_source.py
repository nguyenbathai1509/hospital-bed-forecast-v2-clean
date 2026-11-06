from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from typing import Iterable

import pandas as pd

from src.contracts import SOURCE_COLUMNS, SOURCE_TO_NORMALIZED


@dataclass(frozen=True)
class ExcelBatch:
    rows: list[dict]
    source_files: list[str]
    data_version: str


def _canonical_hash(row: dict) -> str:
    payload = {
        key: (value.isoformat() if hasattr(value, "isoformat") else value)
        for key, value in row.items()
        if key not in {"source_file", "source_row_num", "source_hash"}
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_one(path: Path) -> list[dict]:
    df = pd.read_excel(path, sheet_name="Export Worksheet", engine="openpyxl")
    actual = list(df.columns)
    if actual != SOURCE_COLUMNS:
        missing = [c for c in SOURCE_COLUMNS if c not in actual]
        extra = [c for c in actual if c not in SOURCE_COLUMNS]
        raise ValueError(
            f"DQ01 schema mismatch in {path.name}. "
            f"Expected exactly 16 columns in V2 order. Missing={missing}; extra={extra}; actual={actual}"
        )

    df = df.rename(columns=SOURCE_TO_NORMALIZED)
    df["business_date"] = pd.to_datetime(df["business_date"], errors="raise").dt.date

    int_cols = [
        "source_month", "department_id", "planned_beds", "occupied_start", "admissions",
        "transfer_in", "discharges", "transfer_out", "occupied_end", "occupied_beds",
    ]
    for col in int_cols:
        if df[col].isna().any():
            continue
        df[col] = df[col].astype(int)

    rows: list[dict] = []
    for idx, rec in enumerate(df.to_dict(orient="records"), start=2):
        normalized = {
            k: (None if pd.isna(v) else v)
            for k, v in rec.items()
        }
        normalized["source_file"] = path.name
        normalized["source_row_num"] = idx
        normalized["source_hash"] = _canonical_hash(normalized)
        rows.append(normalized)
    return rows


def load_excel_bootstrap(paths: Iterable[str | Path]) -> ExcelBatch:
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("At least one Excel source file is required")
    all_rows: list[dict] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        all_rows.extend(_read_one(path))

    digest = hashlib.sha256()
    for row in sorted(all_rows, key=lambda r: (r["business_date"], r["department_id"])):
        digest.update(row["source_hash"].encode("ascii"))
    return ExcelBatch(
        rows=all_rows,
        source_files=[p.name for p in paths],
        data_version=f"excel-sha256:{digest.hexdigest()}",
    )
