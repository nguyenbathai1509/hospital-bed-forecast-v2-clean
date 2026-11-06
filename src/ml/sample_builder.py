from __future__ import annotations

from datetime import timedelta
from typing import Iterable


HORIZONS = (1, 3)


def build_ml_samples(
    feature_rows: Iterable[dict],
    clean_rows: Iterable[dict],
    feature_version: str,
    data_version: str,
) -> list[dict]:
    feature_rows = list(feature_rows)
    clean_rows = list(clean_rows)

    # Actual được lookup bằng DATE thật + department.
    # Không dùng "dòng thứ h phía sau", vì nếu timeline lỗi
    # cách đó có thể tạo target sai.
    actual_by_key = {
        (
            r["business_date"],
            int(r["department_id"]),
        ): int(r["occupied_beds"])
        for r in clean_rows
    }

    samples: list[dict] = []

    for feature_row in feature_rows:
        # Bộ feature tabular V2 yêu cầu đủ lag 1/2/3.
        # lag_3 chính là gate cho ba ngày đầu chuỗi.
        if feature_row.get("occupied_beds_lag_3") is None:
            continue

        origin_date = feature_row["origin_date"]
        department_id = int(
            feature_row["department_id"]
        )

        for horizon in HORIZONS:
            target_date = (
                origin_date
                + timedelta(days=horizon)
            )

            target = actual_by_key.get(
                (
                    target_date,
                    department_id,
                )
            )

            # Target chưa mature thì không phải training sample.
            if target is None:
                continue

            samples.append(
                {
                    "origin_date": origin_date,
                    "department_id": department_id,
                    "horizon": horizon,
                    "target_date": target_date,
                    "target_occupied_beds": target,
                    "feature_version": feature_version,
                    "data_version": data_version,
                }
            )

    samples.sort(
        key=lambda row: (
            row["horizon"],
            row["target_date"],
            row["department_id"],
        )
    )

    return samples