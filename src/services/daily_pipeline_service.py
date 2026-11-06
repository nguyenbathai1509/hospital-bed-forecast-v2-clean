from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import uuid

from src.config import settings
from src.db.engine import create_sql_engine
from src.db.repositories.core import CoreRepository
from src.features.builder import build_features
from src.ml.sample_builder import build_ml_samples
from src.monitoring.service import (
    run_actual_matching,
    run_production_monitoring,
)
from src.promotion.service import (
    activate_due_scheduled_models,
)
from src.quality.rules import (
    has_error,
    severity_counts,
    validate_rows,
)
from src.sources.base import SourceAdapter
from src.sources.excel_adapter import (
    ExcelSourceAdapter,
)


def _new_run_id(
    prefix: str = "DAY",
) -> str:
    return (
        f"{prefix}_"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


def _finish_failed(
    engine,
    run_id: str,
    rows: int,
    counts: dict[str, int],
    message: str,
) -> None:
    with engine.begin() as conn:
        CoreRepository(
            conn
        ).finish_pipeline_run(
            run_id,
            "FAILED",
            rows,
            counts,
            message[:4000],
        )


def run_daily_pipeline(
    source: SourceAdapter,
) -> dict:
    """Run the V2 Daily Data Pipeline through Actual Matching and Monitoring.

    V2-18 lifecycle:
        SOURCE_READINESS
        -> EXTRACT_RAW
        -> DATA_QUALITY
        -> CLEAN
        -> FEATURE
        -> ML_SAMPLES
        -> PRODUCTION_CYCLE_ACTIVATION
        -> ACTUAL_MATCHING
        -> MONITORING
        -> DATA_READY

    Actual Matching only uses immutable Official Forecasts. If an Official target_date
    is later than the latest CLEAN Actual for its department, it remains
    WAITING_FOR_ACTUAL; the pipeline never fabricates future Actual values.
    """

    run_id = _new_run_id()

    readiness = (
        source.check_readiness()
    )

    source_ref = (
        source.source_ref
    )

    data_version = (
        readiness.details.get(
            "data_version"
        )
        if readiness.details
        else None
    )

    engine = (
        create_sql_engine()
    )

    with engine.begin() as conn:
        CoreRepository(
            conn
        ).create_pipeline_run(
            run_id=run_id,
            source_mode=(
                source.source_mode
            ),
            source_ref=(
                source_ref
            ),
            data_version=(
                data_version
            ),
            business_date=(
                readiness.business_date
            ),
        )

    if not readiness.ready:
        terminal = (
            "FAILED"
            if readiness.reason
            == "SOURCE_UNREADABLE_OR_SCHEMA_INVALID"
            else "WAITING"
        )

        with engine.begin() as conn:
            CoreRepository(
                conn
            ).finish_pipeline_run(
                run_id,
                terminal,
                0,
                {
                    "ERROR": 0,
                    "WARNING": 0,
                    "CHECK": 0,
                },
                (
                    "Source readiness failed: "
                    f"{readiness.reason}; "
                    f"details={readiness.details}"
                ),
            )

        return {
            "run_id": run_id,
            "status": terminal,
            "business_date": (
                None
                if readiness.business_date
                is None
                else str(
                    readiness.business_date
                )
            ),
            "readiness": {
                "ready": False,
                "reason": (
                    readiness.reason
                ),
                "details": (
                    readiness.details
                ),
            },
            "stages": {
                "SOURCE_READINESS": (
                    terminal
                ),
            },
        }

    stages: dict[
        str,
        object,
    ] = {
        "SOURCE_READINESS": "PASS",
        "EXTRACT_RAW": "PENDING",
        "DATA_QUALITY": "PENDING",
        "CLEAN": "PENDING",
        "FEATURE": "PENDING",
        "ML_SAMPLES": "PENDING",
        "PRODUCTION_CYCLE_ACTIVATION": (
            "PENDING"
        ),
        "ACTUAL_MATCHING": (
            "PENDING"
        ),
        "MONITORING": (
            "PENDING"
        ),
    }

    rows_extracted = 0

    counts = {
        "ERROR": 0,
        "WARNING": 0,
        "CHECK": 0,
    }

    try:
        batch = (
            source.extract()
        )

        rows_extracted = len(
            batch.rows
        )

        data_version = (
            batch.data_version
        )

        # Stage 1: RAW + DQ + CLEAN.
        # DQ is evaluated on the full current RAW snapshot so continuity and late
        # corrections remain visible even when a future source adapter is incremental.
        with engine.begin() as conn:
            repo = (
                CoreRepository(
                    conn
                )
            )

            repo.upsert_departments(
                batch.rows
            )

            raw_stats = (
                repo.upsert_raw(
                    batch.rows,
                    run_id,
                )
            )

            stages[
                "EXTRACT_RAW"
            ] = {
                "status": "PASS",
                **raw_stats,
                "extracted": (
                    rows_extracted
                ),
            }

            raw_snapshot = (
                repo.fetch_raw_rows()
            )

            issues = (
                validate_rows(
                    raw_snapshot,
                    schema_passed=True,
                )
            )

            counts = (
                severity_counts(
                    issues
                )
            )

            repo.replace_issues_for_run(
                run_id,
                issues,
            )

            stages[
                "DATA_QUALITY"
            ] = {
                "status": (
                    "PASS"
                    if not has_error(
                        issues
                    )
                    else "ERROR"
                ),
                **counts,
            }

            if has_error(
                issues
            ):
                repo.finish_pipeline_run(
                    run_id,
                    "FAILED",
                    rows_extracted,
                    counts,
                    (
                        "Data Quality ERROR; "
                        "downstream CLEAN/FEATURE/ML/"
                        "Actual Matching/Monitoring "
                        "was not refreshed."
                    ),
                )

                stages[
                    "CLEAN"
                ] = "BLOCKED_BY_DQ_ERROR"

                stages[
                    "FEATURE"
                ] = "BLOCKED_BY_DQ_ERROR"

                stages[
                    "ML_SAMPLES"
                ] = "BLOCKED_BY_DQ_ERROR"

                stages[
                    "PRODUCTION_CYCLE_ACTIVATION"
                ] = "BLOCKED_BY_DQ_ERROR"

                stages[
                    "ACTUAL_MATCHING"
                ] = "BLOCKED_BY_DQ_ERROR"

                stages[
                    "MONITORING"
                ] = "BLOCKED_BY_DQ_ERROR"

                return {
                    "run_id": run_id,
                    "status": "FAILED",
                    "business_date": str(
                        readiness.business_date
                    ),
                    "data_version": (
                        data_version
                    ),
                    "quality": counts,
                    "stages": stages,
                }

            issue_by_key = (
                defaultdict(
                    list
                )
            )

            for issue in issues:
                if (
                    issue.business_date
                    is not None
                    and issue.department_id
                    is not None
                ):
                    issue_by_key[
                        (
                            issue.business_date,
                            issue.department_id,
                        )
                    ].append(
                        issue
                    )

            repo.upsert_clean(
                raw_snapshot,
                run_id,
                issue_by_key,
            )

            stages[
                "CLEAN"
            ] = {
                "status": "PASS",
                "rows": len(
                    raw_snapshot
                ),
            }

        # Stage 2: safe full rebuild of features + mature ML samples.
        # With the current small bootstrap dataset this guarantees that a late source
        # correction propagates through lag/rolling features and target maturation.
        with engine.begin() as conn:
            repo = (
                CoreRepository(
                    conn
                )
            )

            clean_rows = (
                repo.fetch_clean_rows()
            )

            feature_rows = (
                build_features(
                    clean_rows,
                    settings.feature_version,
                )
            )

            feature_count = (
                repo.replace_features(
                    feature_rows,
                    settings.feature_version,
                )
            )

            stages[
                "FEATURE"
            ] = {
                "status": "PASS",
                "rows": (
                    feature_count
                ),
                "feature_version": (
                    settings.feature_version
                ),
                "rebuild_mode": (
                    "FULL_SAFE_REBUILD"
                ),
            }

            sample_rows = (
                build_ml_samples(
                    feature_rows=(
                        feature_rows
                    ),
                    clean_rows=(
                        clean_rows
                    ),
                    feature_version=(
                        settings.feature_version
                    ),
                    data_version=(
                        data_version
                    ),
                )
            )

            sample_counts = (
                repo.replace_ml_samples(
                    sample_rows,
                    settings.feature_version,
                )
            )

            stages[
                "ML_SAMPLES"
            ] = {
                "status": "PASS",
                "h1": (
                    sample_counts.get(
                        1,
                        0,
                    )
                ),
                "h3": (
                    sample_counts.get(
                        3,
                        0,
                    )
                ),
            }

        # V2-16:
        # Activate due NEXT_CYCLE candidate only when this
        # business_date+horizon has not already been frozen.
        stages[
            "PRODUCTION_CYCLE_ACTIVATION"
        ] = (
            activate_due_scheduled_models(
                readiness.business_date
            )
        )

        # V2-18:
        # Official Forecast -> CLEAN Actual evidence.
        # WAITING_FOR_ACTUAL is a valid non-error state.
        stages[
            "ACTUAL_MATCHING"
        ] = (
            run_actual_matching()
        )

        # V2-18:
        # Cumulative monitoring snapshot from matched Official evidence only.
        stages[
            "MONITORING"
        ] = (
            run_production_monitoring(
                pipeline_run_id=(
                    run_id
                ),
                business_date=(
                    readiness.business_date
                ),
            )
        )

        with engine.begin() as conn:
            CoreRepository(
                conn
            ).finish_pipeline_run(
                run_id,
                "DATA_READY",
                rows_extracted,
                counts,
            )

        return {
            "run_id": run_id,
            "status": "DATA_READY",
            "business_date": str(
                readiness.business_date
            ),
            "data_version": (
                data_version
            ),
            "feature_version": (
                settings.feature_version
            ),
            "rows": (
                rows_extracted
            ),
            "quality": counts,
            "stages": stages,
        }

    except Exception as exc:
        _finish_failed(
            engine,
            run_id,
            rows_extracted,
            counts,
            (
                "Unhandled pipeline error: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

        stages[
            "FAILED_AT"
        ] = next(
            (
                key
                for key, value
                in stages.items()
                if value == "PENDING"
            ),
            "UNKNOWN",
        )

        return {
            "run_id": (
                run_id
            ),
            "status": (
                "FAILED"
            ),
            "business_date": (
                None
                if readiness.business_date
                is None
                else str(
                    readiness.business_date
                )
            ),
            "data_version": (
                data_version
            ),
            "quality": (
                counts
            ),
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            "stages": (
                stages
            ),
        }


def run_daily_excel_pipeline(
    noi_path: str | Path,
    ngoai_path: str | Path,
) -> dict:
    return run_daily_pipeline(
        ExcelSourceAdapter(
            [
                noi_path,
                ngoai_path,
            ]
        )
    )