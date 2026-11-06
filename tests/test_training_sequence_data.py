from datetime import (
    date,
    timedelta,
)

from src.training.data import (
    build_sequence_frame,
)


def test_sequence_builder_creates_3x12_tensor_for_two_departments():
    feature_rows = []

    for dep in (
        343,
        344,
    ):
        for i in range(5):
            day = (
                date(
                    2026,
                    1,
                    1,
                )
                + timedelta(
                    days=i
                )
            )

            feature_rows.append(
                {
                    "origin_date": (
                        day
                    ),
                    "department_id": (
                        dep
                    ),
                    "planned_beds": (
                        55
                        if dep == 343
                        else 45
                    ),
                    "occupied_beds": (
                        40 + i
                    ),
                    "admissions": 2,
                    "discharges": 1,
                    "transfer_in": 1,
                    "transfer_out": 1,
                    "net_flow": 1,
                    "is_weekend": 0,
                    "dow_sin": 0.1,
                    "dow_cos": 0.2,
                }
            )

    sample_rows = [
        {
            "origin_date": (
                date(
                    2026,
                    1,
                    4,
                )
            ),
            "department_id": (
                343
            ),
            "horizon": 1,
            "target_date": (
                date(
                    2026,
                    1,
                    5,
                )
            ),
            "target_occupied_beds": (
                44
            ),
        }
    ]

    frame = build_sequence_frame(
        feature_rows,
        sample_rows,
        department_categories=(
            343,
            344,
        ),
    )

    sequence = (
        frame.iloc[0][
            "sequence"
        ]
    )

    assert (
        sequence.shape
        == (3, 12)
    )

    assert (
        sequence[
            0,
            -2:,
        ].tolist()
        == [
            1.0,
            0.0,
        ]
    )