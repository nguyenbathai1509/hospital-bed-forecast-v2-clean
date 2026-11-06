from datetime import (
    date,
    timedelta,
)

from src.features.builder import (
    build_features,
)
from src.ml.sample_builder import (
    build_ml_samples,
)


def _rows(
    n: int = 8,
):
    rows = []

    for i in range(n):
        business_date = (
            date(2026, 1, 1)
            + timedelta(days=i)
        )

        rows.append(
            {
                "business_date": (
                    business_date
                ),
                "department_id": 1,
                "planned_beds": 20,
                "occupied_beds": (
                    10 + i
                ),
                "admissions": 2,
                "discharges": 1,
                "transfer_in": 0,
                "transfer_out": 1,
                "source_revision_no": 1,
            }
        )

    return rows


def test_ml_samples_require_lag3_and_mature_target():
    clean_rows = _rows(8)

    feature_rows = build_features(
        clean_rows,
        "v2.0",
    )

    samples = build_ml_samples(
        feature_rows,
        clean_rows,
        "v2.0",
        "dv",
    )

    h1 = [
        sample
        for sample in samples
        if sample["horizon"] == 1
    ]

    h3 = [
        sample
        for sample in samples
        if sample["horizon"] == 3
    ]

    # Origin đầu tiên đủ lag3 là 04/01.
    #
    # Với 8 ngày dữ liệu:
    # H1 mature tới origin 07/01.
    # H3 mature tới origin 05/01.
    assert [
        sample["origin_date"]
        for sample in h1
    ] == [
        date(2026, 1, day)
        for day in (
            4,
            5,
            6,
            7,
        )
    ]

    assert [
        sample["origin_date"]
        for sample in h3
    ] == [
        date(2026, 1, day)
        for day in (
            4,
            5,
        )
    ]

    assert (
        h1[0]["target_date"]
        == date(2026, 1, 5)
    )

    assert (
        h3[0]["target_date"]
        == date(2026, 1, 7)
    )