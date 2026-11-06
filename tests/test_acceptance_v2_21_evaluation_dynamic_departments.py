from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.evaluation.service import (
    _expected_test_department_counts,
    _prediction_rows,
)
from src.training.config import (
    TemporalSplitSpec,
)


ROWS_PER_DEPARTMENT = 37


def _candidate():
    return {
        "candidate_id":
            "TRN_DYNAMIC_DEPT_H1_RF",
        "horizon": 1,
        "model_family": "RF",
        "feature_version": "v2.0",
        "data_version": "TEST",
        "mae": 0.0,
    }


def _test_frame(
    departments,
):
    rows = []

    start = date(
        2026,
        5,
        25,
    )

    for department_id in departments:
        for index in range(
            ROWS_PER_DEPARTMENT
        ):
            target_date = (
                start
                + timedelta(
                    days=index
                )
            )

            rows.append(
                {
                    "origin_date":
                        target_date,
                    "target_date":
                        target_date,
                    "department_id":
                        department_id,
                    "target_occupied_beds":
                        50.0,
                }
            )

    return pd.DataFrame(
        rows
    )


def test_three_departments_are_supported():
    frame = _test_frame(
        [343, 344, 345]
    )

    predictions = np.full(
        len(frame),
        50.0,
    )

    rows, summary = (
        _prediction_rows(
            test_frame=frame,
            predictions=predictions,
            candidate=_candidate(),
            run_id="TRN_3DEPT",
            expected_department_counts={
                343: 37,
                344: 37,
                345: 37,
            },
        )
    )

    assert len(rows) == 111
    assert summary.row_count == 111
    assert summary.replay_mae == 0.0


def test_missing_expected_department_is_rejected():
    frame = _test_frame(
        [343, 344]
    )

    predictions = np.full(
        len(frame),
        50.0,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "does not match historical "
            "ML samples"
        ),
    ):
        _prediction_rows(
            test_frame=frame,
            predictions=predictions,
            candidate=_candidate(),
            run_id="TRN_MISSING_DEPT",
            expected_department_counts={
                343: 37,
                344: 37,
                345: 37,
            },
        )


def test_two_department_contract_remains_74_rows():
    frame = _test_frame(
        [343, 344]
    )

    predictions = np.full(
        len(frame),
        50.0,
    )

    rows, summary = (
        _prediction_rows(
            test_frame=frame,
            predictions=predictions,
            candidate=_candidate(),
            run_id="TRN_2DEPT",
            expected_department_counts={
                343: 37,
                344: 37,
            },
        )
    )

    assert len(rows) == 74
    assert summary.row_count == 74


def test_expected_departments_come_from_historical_test_samples():
    spec = TemporalSplitSpec(
        train_end=date(
            2026,
            1,
            1,
        ),
        validation_start=date(
            2026,
            1,
            2,
        ),
        validation_end=date(
            2026,
            1,
            2,
        ),
        test_start=date(
            2026,
            1,
            3,
        ),
        test_end=date(
            2026,
            2,
            8,
        ),
    )

    sample_rows = []

    for department_id in (
        343,
        344,
        345,
    ):
        sample_rows.append(
            {
                "department_id":
                    department_id,
                "target_date":
                    date(
                        2026,
                        1,
                        1,
                    ),
            }
        )

        sample_rows.append(
            {
                "department_id":
                    department_id,
                "target_date":
                    date(
                        2026,
                        1,
                        2,
                    ),
            }
        )

        for index in range(
            ROWS_PER_DEPARTMENT
        ):
            sample_rows.append(
                {
                    "department_id":
                        department_id,
                    "target_date": (
                        date(
                            2026,
                            1,
                            3,
                        )
                        + timedelta(
                            days=index
                        )
                    ),
                }
            )

    counts = (
        _expected_test_department_counts(
            sample_rows=sample_rows,
            split_spec=spec,
        )
    )

    assert counts == {
        343: 37,
        344: 37,
        345: 37,
    }
