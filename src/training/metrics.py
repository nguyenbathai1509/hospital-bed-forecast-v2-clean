from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
)

import numpy as np

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)


@dataclass(frozen=True)
class RegressionMetrics:
    sample_count: int
    mae: float
    rmse: float
    wape: float
    r2: float | None
    bias: float
    p90_abs_error: float
    max_abs_error: float
    within_2_rate: float
    underprediction_rate: float
    underprediction_mae: float

    def as_dict(
        self,
    ) -> dict:
        return asdict(
            self
        )


def compute_regression_metrics(
    y_true,
    y_pred,
) -> RegressionMetrics:
    actual = np.asarray(
        y_true,
        dtype=float,
    ).reshape(-1)

    pred = np.asarray(
        y_pred,
        dtype=float,
    ).reshape(-1)

    if actual.shape != pred.shape:
        raise ValueError(
            "Shape mismatch: "
            f"actual={actual.shape}, "
            f"pred={pred.shape}"
        )

    if actual.size == 0:
        raise ValueError(
            "Cannot compute metrics on zero rows"
        )

    if (
        not np.isfinite(
            actual
        ).all()
        or not np.isfinite(
            pred
        ).all()
    ):
        raise ValueError(
            "Metrics require finite actual "
            "and prediction values"
        )

    residual = (
        actual
        - pred
    )

    abs_error = np.abs(
        residual
    )

    denom = float(
        np.abs(
            actual
        ).sum()
    )

    wape = (
        0.0
        if denom == 0.0
        else float(
            abs_error.sum()
            / denom
            * 100.0
        )
    )

    under_mask = (
        pred
        < actual
    )

    if under_mask.any():
        under_mae = float(
            np.mean(
                actual[
                    under_mask
                ]
                - pred[
                    under_mask
                ]
            )
        )
    else:
        under_mae = 0.0

    if (
        actual.size < 2
        or np.allclose(
            actual,
            actual[0],
        )
    ):
        r2 = None
    else:
        r2 = float(
            r2_score(
                actual,
                pred,
            )
        )

    return RegressionMetrics(
        sample_count=int(
            actual.size
        ),
        mae=float(
            mean_absolute_error(
                actual,
                pred,
            )
        ),
        rmse=float(
            np.sqrt(
                mean_squared_error(
                    actual,
                    pred,
                )
            )
        ),
        wape=wape,
        r2=r2,
        bias=float(
            np.mean(
                residual
            )
        ),
        p90_abs_error=float(
            np.quantile(
                abs_error,
                0.90,
            )
        ),
        max_abs_error=float(
            np.max(
                abs_error
            )
        ),
        within_2_rate=float(
            np.mean(
                abs_error
                <= 2.0
            )
        ),
        underprediction_rate=float(
            np.mean(
                under_mask
            )
        ),
        underprediction_mae=(
            under_mae
        ),
    )


def compute_metrics_by_department(
    department_ids,
    y_true,
    y_pred,
) -> dict[
    int,
    RegressionMetrics,
]:
    departments = np.asarray(
        department_ids
    ).reshape(-1)

    actual = np.asarray(
        y_true,
        dtype=float,
    ).reshape(-1)

    pred = np.asarray(
        y_pred,
        dtype=float,
    ).reshape(-1)

    if not (
        departments.size
        == actual.size
        == pred.size
    ):
        raise ValueError(
            "department_ids, y_true "
            "and y_pred must have equal length"
        )

    result: dict[
        int,
        RegressionMetrics,
    ] = {}

    for department_id in sorted(
        {
            int(x)
            for x
            in departments.tolist()
        }
    ):
        mask = (
            departments.astype(int)
            == department_id
        )

        result[
            department_id
        ] = compute_regression_metrics(
            actual[mask],
            pred[mask],
        )

    return result