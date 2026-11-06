from datetime import date
import math

from src.features.builder import (
    build_features,
)


def _clean_rows():
    occupied = [
        10,
        11,
        13,
        12,
        14,
    ]

    admissions = [
        2,
        3,
        4,
        5,
        6,
    ]

    discharges = [
        1,
        2,
        1,
        3,
        2,
    ]

    rows = []

    for i in range(5):
        business_date = date(
            2026,
            1,
            1 + i,
        )

        rows.append(
            {
                "business_date": (
                    business_date
                ),
                "department_id": 1,
                "planned_beds": 20,
                "occupied_beds": (
                    occupied[i]
                ),
                "admissions": (
                    admissions[i]
                ),
                "discharges": (
                    discharges[i]
                ),
                "transfer_in": 1,
                "transfer_out": 1,
                "source_revision_no": 1,
            }
        )

    return rows


def test_v2_feature_lag_and_rolling_contract():
    features = build_features(
        _clean_rows(),
        "v2.0",
    )

    assert len(features) == 5

    assert (
        features[0][
            "occupied_beds_lag_1"
        ]
        is None
    )

    assert (
        features[2][
            "occupied_beds_lag_3"
        ]
        is None
    )

    assert (
        features[3][
            "occupied_beds_lag_1"
        ]
        == 13
    )

    assert (
        features[3][
            "occupied_beds_lag_2"
        ]
        == 11
    )

    assert (
        features[3][
            "occupied_beds_lag_3"
        ]
        == 10
    )

    # Rolling origin 04/01 gồm:
    # [11, 13, 12]
    assert math.isclose(
        features[3][
            "occupied_beds_mean_3"
        ],
        12.0,
    )

    # Population std, ddof = 0.
    assert math.isclose(
        features[3][
            "occupied_beds_std_3"
        ],
        math.sqrt(2 / 3),
        rel_tol=1e-12,
    )

    # Ngày thứ 4:
    # admissions=5
    # transfer_in=1
    # discharges=3
    # transfer_out=1
    #
    # net_flow = 5 + 1 - 3 - 1 = 2
    assert (
        features[3]["net_flow"]
        == 2
    )