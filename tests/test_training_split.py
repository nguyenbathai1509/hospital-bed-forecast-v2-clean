from datetime import (
    date,
    timedelta,
)

import pandas as pd

from src.training.data import (
    split_by_target_date,
)


def test_temporal_split_uses_target_date_and_no_shuffle():
    dates = [
        date(
            2026,
            4,
            25,
        )
        + timedelta(
            days=i
        )
        for i
        in range(32)
    ]

    frame = pd.DataFrame(
        {
            "target_date": (
                dates
            ),
            "value": list(
                range(
                    len(dates)
                )
            ),
        }
    )

    parts = (
        split_by_target_date(
            frame
        )
    )

    assert (
        max(
            parts.train[
                "target_date"
            ]
        )
        <= date(
            2026,
            4,
            26,
        )
    )

    assert (
        min(
            parts.validation[
                "target_date"
            ]
        )
        == date(
            2026,
            4,
            27,
        )
    )

    assert (
        max(
            parts.validation[
                "target_date"
            ]
        )
        == date(
            2026,
            5,
            24,
        )
    )

    assert (
        min(
            parts.test[
                "target_date"
            ]
        )
        == date(
            2026,
            5,
            25,
        )
    )