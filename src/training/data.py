from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from src.features.builder import FEATURE_VALUE_COLUMNS
from src.training.config import SPLIT_SPEC, TemporalSplitSpec


TABULAR_FEATURE_COLUMNS = tuple(FEATURE_VALUE_COLUMNS)
TABULAR_CATEGORICAL_COLUMNS = ("department_id",)
TABULAR_NUMERIC_COLUMNS = tuple(
    name
    for name in TABULAR_FEATURE_COLUMNS
    if name not in TABULAR_CATEGORICAL_COLUMNS
)

SEQUENCE_BASE_NUMERIC_COLUMNS = (
    "planned_beds",
    "occupied_beds",
    "admissions",
    "discharges",
    "transfer_in",
    "transfer_out",
    "net_flow",
    "is_weekend",
    "dow_sin",
    "dow_cos",
)


@dataclass(frozen=True)
class TemporalPartitions:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame

    @property
    def development(self) -> pd.DataFrame:
        return pd.concat(
            [
                self.train,
                self.validation,
            ],
            ignore_index=True,
        )


def split_by_target_date(
    frame: pd.DataFrame,
    spec: TemporalSplitSpec = SPLIT_SPEC,
) -> TemporalPartitions:
    if "target_date" not in frame.columns:
        raise ValueError(
            "target_date column is required for temporal split"
        )

    df = frame.copy()

    df["target_date"] = pd.to_datetime(
        df["target_date"]
    ).dt.date

    if df["target_date"].isna().any():
        raise ValueError("target_date must not contain missing dates")

    train = df[
        df["target_date"]
        <= spec.train_end
    ].copy()

    validation = df[
        (
            df["target_date"]
            >= spec.validation_start
        )
        &
        (
            df["target_date"]
            <= spec.validation_end
        )
    ].copy()

    test = df[
        (
            df["target_date"]
            >= spec.test_start
        )
        &
        (
            df["target_date"]
            <= spec.test_end
        )
    ].copy()

    if (
        len(train)
        + len(validation)
        + len(test)
        != len(df)
    ):
        uncovered = df[
            ~df.index.isin(train.index)
            & ~df.index.isin(
                validation.index
            )
            & ~df.index.isin(test.index)
        ]

        raise ValueError(
            "Temporal split does not cover all rows; "
            "uncovered target dates="
            f"{sorted(set(uncovered['target_date']))}"
        )

    if (
        train.empty
        or validation.empty
        or test.empty
    ):
        raise ValueError(
            "Temporal split requires non-empty "
            "train/validation/test; "
            f"got {len(train)}/"
            f"{len(validation)}/"
            f"{len(test)}"
        )

    return TemporalPartitions(
        train=train.reset_index(
            drop=True
        ),
        validation=validation.reset_index(
            drop=True
        ),
        test=test.reset_index(
            drop=True
        ),
    )


def feature_contract_hash(
    feature_version: str,
) -> str:
    payload = {
        "feature_version": (
            feature_version
        ),
        "tabular_feature_order": list(
            TABULAR_FEATURE_COLUMNS
        ),
        "sequence_base_numeric_columns": list(
            SEQUENCE_BASE_NUMERIC_COLUMNS
        ),
        "sequence_length": 3,
        "department_encoding": "ONE_HOT",
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def build_sequence_frame(
    feature_rows: list[dict],
    sample_rows: list[dict],
    department_categories: (
        tuple[int, ...]
        | None
    ) = None,
) -> pd.DataFrame:
    if not feature_rows or not sample_rows:
        return pd.DataFrame(
            columns=[
                "origin_date",
                "department_id",
                "horizon",
                "target_date",
                "target_occupied_beds",
                "sequence",
            ]
        )

    if department_categories is None:
        department_categories = tuple(
            sorted(
                {
                    int(
                        row[
                            "department_id"
                        ]
                    )
                    for row
                    in feature_rows
                }
            )
        )

    if not department_categories:
        raise ValueError(
            "department_categories cannot be empty"
        )

    feature_by_key: dict[
        tuple,
        dict,
    ] = {}

    for row in feature_rows:
        origin = pd.Timestamp(
            row["origin_date"]
        ).date()

        feature_by_key[
            (
                origin,
                int(
                    row[
                        "department_id"
                    ]
                ),
            )
        ] = row

    records = []

    for sample in sample_rows:
        origin = pd.Timestamp(
            sample["origin_date"]
        ).date()

        department_id = int(
            sample["department_id"]
        )

        steps: list[
            list[float]
        ] = []

        for offset in (
            2,
            1,
            0,
        ):
            step_date = (
                origin
                - timedelta(
                    days=offset
                )
            )

            row = feature_by_key.get(
                (
                    step_date,
                    department_id,
                )
            )

            if row is None:
                raise ValueError(
                    "Missing sequence history for "
                    f"department={department_id}, "
                    f"origin={origin}, "
                    f"step={step_date}"
                )

            numeric = [
                float(row[name])
                for name
                in SEQUENCE_BASE_NUMERIC_COLUMNS
            ]

            one_hot = [
                (
                    1.0
                    if department_id
                    == category
                    else 0.0
                )
                for category
                in department_categories
            ]

            steps.append(
                numeric
                + one_hot
            )

        sequence = np.asarray(
            steps,
            dtype=float,
        )

        expected_width = (
            len(
                SEQUENCE_BASE_NUMERIC_COLUMNS
            )
            + len(
                department_categories
            )
        )

        if sequence.shape != (
            3,
            expected_width,
        ):
            raise ValueError(
                "Unexpected sequence shape "
                f"{sequence.shape}; "
                "expected "
                f"(3, {expected_width})"
            )

        records.append(
            {
                "origin_date": (
                    origin
                ),
                "department_id": (
                    department_id
                ),
                "horizon": int(
                    sample["horizon"]
                ),
                "target_date": (
                    pd.Timestamp(
                        sample[
                            "target_date"
                        ]
                    ).date()
                ),
                "target_occupied_beds": float(
                    sample[
                        "target_occupied_beds"
                    ]
                ),
                "sequence": sequence,
            }
        )

    return pd.DataFrame(
        records
    )
