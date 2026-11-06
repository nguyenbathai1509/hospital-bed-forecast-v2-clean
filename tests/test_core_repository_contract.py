from src.db.repositories.core import CoreRepository


REQUIRED_V2_12_METHODS = (
    "create_pipeline_run",
    "finish_pipeline_run",
    "upsert_departments",
    "upsert_raw",
    "replace_issues_for_run",
    "upsert_clean",
    "fetch_raw_rows",
    "fetch_clean_rows",
    "replace_features",
    "replace_ml_samples",
    "feature_count",
    "ml_sample_counts",
)


def test_core_repository_exposes_v2_12_contract():
    missing = [
        name
        for name in REQUIRED_V2_12_METHODS
        if not callable(
            getattr(
                CoreRepository,
                name,
                None,
            )
        )
    ]

    assert missing == [], (
        f"Missing CoreRepository methods: {missing}"
    )