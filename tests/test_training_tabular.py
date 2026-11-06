from src.training.data import (
    TABULAR_CATEGORICAL_COLUMNS,
    TABULAR_FEATURE_COLUMNS,
    TABULAR_NUMERIC_COLUMNS,
)


def test_tabular_contract_is_28_features_with_department_categorical():
    assert (
        len(
            TABULAR_FEATURE_COLUMNS
        )
        == 28
    )

    assert (
        TABULAR_CATEGORICAL_COLUMNS
        == (
            "department_id",
        )
    )

    assert (
        "department_id"
        not in TABULAR_NUMERIC_COLUMNS
    )

    assert (
        len(
            TABULAR_NUMERIC_COLUMNS
        )
        == 27
    )