from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


TRAINING_CONTRACT_VERSION = "v2.1"
DEFAULT_RANDOM_SEED = 42
EXPECTED_FAMILIES = ("RF", "XGBOOST", "SVR", "LSTM")
EXPECTED_HORIZONS = (1, 3)
DEFAULT_VALIDATION_DAYS = 28
DEFAULT_TEST_DAYS = 37


@dataclass(frozen=True)
class TemporalSplitSpec:
    train_end: date = date(2026, 4, 26)
    validation_start: date = date(2026, 4, 27)
    validation_end: date = date(2026, 5, 24)
    test_start: date = date(2026, 5, 25)
    test_end: date = date(2026, 6, 30)

    def __post_init__(self) -> None:
        if not (
            self.train_end < self.validation_start
            <= self.validation_end < self.test_start <= self.test_end
        ):
            raise ValueError("Temporal split windows must be ordered and non-overlapping")
        if (
            self.validation_start != self.train_end + timedelta(days=1)
            or self.test_start != self.validation_end + timedelta(days=1)
        ):
            raise ValueError("Temporal split windows must be contiguous")

    @classmethod
    def ending_at(
        cls,
        test_end: date,
        *,
        validation_days: int = DEFAULT_VALIDATION_DAYS,
        test_days: int = DEFAULT_TEST_DAYS,
    ) -> TemporalSplitSpec:
        """Resolve calendar windows once from mature data, never the wall clock."""
        for name, value in (("validation_days", validation_days), ("test_days", test_days)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        test_start = test_end - timedelta(days=test_days - 1)
        validation_end = test_start - timedelta(days=1)
        validation_start = validation_end - timedelta(days=validation_days - 1)
        return cls(
            train_end=validation_start - timedelta(days=1),
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "split_axis": "target_date",
            "shuffle": "false",
        }


# Historical default for callers replaying the original V2 experiment.
# New training resolves a spec from its dataset and persists that exact spec.
SPLIT_SPEC = TemporalSplitSpec()


RF_GRID = {
    "n_estimators": [200, 400],
    "max_depth": [3, 5, None],
    "min_samples_leaf": [2, 4],
    "max_features": [0.7, 1.0],
}

XGBOOST_GRID = {
    "n_estimators": [200, 400],
    "max_depth": [2, 3],
    "learning_rate": [0.03, 0.05],
    "min_child_weight": [3, 5],
    "subsample": [0.8],
    "colsample_bytree": [0.8],
}

SVR_GRID = {
    "C": [1, 10, 30],
    "epsilon": [0.1, 0.2, 0.5],
    "gamma": ["scale", 0.01, 0.1],
}

LSTM_GRID = {
    "units": [16, 32],
    "dropout": [0.0, 0.2],
}

LSTM_SEQUENCE_LENGTH = 3
LSTM_BATCH_SIZE = 16
LSTM_MAX_EPOCHS = 200
LSTM_EARLY_STOPPING_PATIENCE = 15
LSTM_DENSE_UNITS = 16
