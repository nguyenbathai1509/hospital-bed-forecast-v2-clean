from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
import uuid

from src.db.engine import create_sql_engine
from src.forecast.contracts import (
    OFFICIAL_CONFIRMATION_PHRASE,
    ForecastPrediction,
)
from src.forecast.engine import (
    build_forecast_value,
    normalize_preview_mode,
)
from src.forecast.repository import ForecastRepository
from src.predictors.factory import create_predictor
from src.registry.contracts import ModelArtifactSpec
from src.registry.repository import ModelRegistryRepository


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


def _new_id(prefix: str) -> str:
    return (
        f"{prefix}_"
        f"{uuid.uuid4().hex.upper()}"
    )


def _normalize_horizons(
    horizons: Iterable[int],
) -> tuple[int, ...]:
    values = tuple(
        dict.fromkeys(
            int(value)
            for value in horizons
        )
    )

    if not values:
        raise ValueError(
            "At least one horizon is required"
        )

    invalid = [
        value
        for value in values
        if value not in {1, 3}
    ]

    if invalid:
        raise ValueError(
            f"Unsupported horizons: {invalid}"
        )

    return values


def _resolve_origin_date(
    repo: ForecastRepository,
    origin_date: date | None,
) -> tuple[date, str | None]:
    context = (
        repo.latest_data_ready_context()
    )

    if context is None:
        raise RuntimeError(
            "No DATA_READY Daily Pipeline run exists"
        )

    latest = context[
        "business_date"
    ]

    resolved = (
        latest
        if origin_date is None
        else origin_date
    )

    if resolved > latest:
        raise ValueError(
            "origin_date cannot be later than "
            f"latest DATA_READY date {latest}"
        )

    return (
        resolved,
        context.get(
            "data_version"
        ),
    )


def _resolve_artifact_spec(
    spec: ModelArtifactSpec,
) -> ModelArtifactSpec:
    path = spec.path

    if not path.is_absolute():
        path = (
            PROJECT_ROOT
            / path
        )

    return replace(
        spec,
        artifact_path=str(
            path.resolve()
        ),
    )


def _candidate_id_for_mode(
    *,
    repo: ForecastRepository,
    mode: str,
    origin_date: date,
    horizon: int,
    custom_candidate_id: str | None,
) -> str:
    if mode == "PRODUCTION":
        locked = (
            repo.daily_lock_candidate_id(
                origin_date=origin_date,
                horizon=horizon,
            )
        )

        if locked is not None:
            return locked

        active = (
            repo.active_production_candidate_id(
                horizon
            )
        )

        if active is None:
            raise RuntimeError(
                f"No ACTIVE Production model for H+{horizon}"
            )

        return active

    if mode == "RECOMMENDED":
        candidate_id = (
            repo.latest_recommended_candidate_id(
                horizon
            )
        )

        if candidate_id is None:
            raise RuntimeError(
                f"No Recommended model for H+{horizon}"
            )

        return candidate_id

    if custom_candidate_id is None:
        raise ValueError(
            "CUSTOM preview requires a candidate_id"
        )

    return custom_candidate_id


def _predict_one(
    *,
    conn,
    origin_date: date,
    department_id: int,
    horizon: int,
    mode: str,
    data_version: str | None,
    custom_candidate_id: str | None = None,
) -> ForecastPrediction:
    repo = ForecastRepository(
        conn
    )

    registry = ModelRegistryRepository(
        conn
    )

    candidate_id = (
        _candidate_id_for_mode(
            repo=repo,
            mode=mode,
            origin_date=origin_date,
            horizon=horizon,
            custom_candidate_id=(
                custom_candidate_id
            ),
        )
    )

    spec = registry.get_candidate(
        candidate_id
    )

    if spec is None:
        raise RuntimeError(
            f"Candidate not found: {candidate_id}"
        )

    if spec.horizon != horizon:
        raise ValueError(
            f"Candidate {candidate_id} belongs to H+{spec.horizon}, "
            f"not H+{horizon}"
        )

    spec = _resolve_artifact_spec(
        spec
    )

    predictor = create_predictor(
        spec
    )

    if spec.inference_type == "TABULAR_28":
        feature_row = repo.feature_row(
            origin_date=origin_date,
            department_id=department_id,
            feature_version=spec.feature_version,
        )

        if feature_row is None:
            raise RuntimeError(
                "Missing tabular features for "
                f"origin={origin_date}, "
                f"department={department_id}, "
                f"feature_version={spec.feature_version}"
            )

        raw = (
            predictor.predict_tabular(
                feature_row
            ).prediction_raw
        )

    elif spec.inference_type == "SEQUENCE_3X12":
        sequence_rows = repo.sequence_rows(
            origin_date=origin_date,
            department_id=department_id,
            feature_version=spec.feature_version,
        )

        if len(sequence_rows) != 3:
            raise RuntimeError(
                "Missing 3-day sequence for "
                f"origin={origin_date}, "
                f"department={department_id}"
            )

        raw = (
            predictor.predict_sequence(
                sequence_rows
            ).prediction_raw
        )

    else:
        raise ValueError(
            "Unsupported inference_type: "
            f"{spec.inference_type}"
        )

    planned_beds = (
        repo.department_planned_beds(
            department_id
        )
    )

    value = build_forecast_value(
        prediction_raw=raw,
        planned_beds=planned_beds,
    )

    return ForecastPrediction(
        origin_date=origin_date,
        department_id=department_id,
        horizon=horizon,
        target_date=(
            origin_date
            + timedelta(days=horizon)
        ),
        candidate_id=spec.candidate_id,
        model_family=spec.model_family,
        source_mode=mode,
        feature_version=spec.feature_version,
        data_version=(
            spec.data_version
            or data_version
        ),
        value=value,
    )


def generate_preview(
    *,
    mode: str = "PRODUCTION",
    origin_date: date | None = None,
    department_ids: Iterable[int] | None = None,
    horizons: Iterable[int] = (1, 3),
    custom_candidates: dict[int, str] | None = None,
) -> dict:
    resolved_mode = normalize_preview_mode(
        mode
    )

    resolved_horizons = (
        _normalize_horizons(
            horizons
        )
    )

    custom_candidates = (
        custom_candidates
        or {}
    )

    engine = create_sql_engine()

    with engine.connect() as conn:
        repo = ForecastRepository(
            conn
        )

        (
            resolved_origin,
            data_version,
        ) = _resolve_origin_date(
            repo,
            origin_date,
        )

        departments = (
            repo.active_department_ids()
            if department_ids is None
            else [
                int(value)
                for value
                in department_ids
            ]
        )

        predictions = [
            _predict_one(
                conn=conn,
                origin_date=resolved_origin,
                department_id=department_id,
                horizon=horizon,
                mode=resolved_mode,
                data_version=data_version,
                custom_candidate_id=(
                    custom_candidates.get(
                        horizon
                    )
                ),
            )
            for horizon in resolved_horizons
            for department_id in departments
        ]

    return {
        "status": "PREVIEW",
        "persisted": False,
        "official": False,
        "monitoring_eligible": False,
        "mode": resolved_mode,
        "origin_date": (
            resolved_origin.isoformat()
        ),
        "prediction_count": len(
            predictions
        ),
        "predictions": [
            item.as_dict()
            for item in predictions
        ],
    }


def create_production_drafts(
    *,
    origin_date: date | None = None,
    department_ids: Iterable[int] | None = None,
    horizons: Iterable[int] = (1, 3),
    created_by: str = "manual",
) -> dict:
    resolved_horizons = (
        _normalize_horizons(
            horizons
        )
    )

    engine = create_sql_engine()

    with engine.connect() as conn:
        repo = ForecastRepository(
            conn
        )

        (
            resolved_origin,
            data_version,
        ) = _resolve_origin_date(
            repo,
            origin_date,
        )

        departments = (
            repo.active_department_ids()
            if department_ids is None
            else [
                int(value)
                for value
                in department_ids
            ]
        )

        predicted = [
            _predict_one(
                conn=conn,
                origin_date=resolved_origin,
                department_id=department_id,
                horizon=horizon,
                mode="PRODUCTION",
                data_version=data_version,
            )
            for horizon in resolved_horizons
            for department_id in departments
        ]

    created: list[dict] = []
    reused: list[dict] = []
    skipped_official: list[dict] = []

    for prediction in predicted:
        with engine.begin() as conn:
            repo = ForecastRepository(
                conn
            )

            official = repo.official_for_key(
                origin_date=(
                    prediction.origin_date
                ),
                department_id=(
                    prediction.department_id
                ),
                horizon=(
                    prediction.horizon
                ),
            )

            if official is not None:
                skipped_official.append(
                    {
                        "origin_date": (
                            prediction.origin_date.isoformat()
                        ),
                        "department_id": (
                            prediction.department_id
                        ),
                        "horizon": (
                            prediction.horizon
                        ),
                        "official_id": (
                            official[
                                "official_id"
                            ]
                        ),
                    }
                )
                continue

            current_candidate = (
                _candidate_id_for_mode(
                    repo=repo,
                    mode="PRODUCTION",
                    origin_date=(
                        prediction.origin_date
                    ),
                    horizon=(
                        prediction.horizon
                    ),
                    custom_candidate_id=None,
                )
            )

            if (
                current_candidate
                != prediction.candidate_id
            ):
                raise RuntimeError(
                    "Production/daily lock changed while Draft was being "
                    "generated; rerun Production Predict"
                )

            existing = repo.open_draft(
                origin_date=(
                    prediction.origin_date
                ),
                department_id=(
                    prediction.department_id
                ),
                horizon=(
                    prediction.horizon
                ),
            )

            if (
                existing is not None
                and existing[
                    "candidate_id"
                ]
                == prediction.candidate_id
            ):
                reused.append(
                    dict(existing)
                )
                continue

            if existing is not None:
                repo.void_open_draft(
                    existing[
                        "draft_id"
                    ]
                )

            row = prediction.as_dict()

            row.update(
                {
                    "draft_id": _new_id(
                        "DRF"
                    ),
                    "created_by": (
                        created_by
                    ),
                }
            )

            repo.insert_draft(
                row
            )

            created.append(
                row
            )

    status = (
        "NO_DRAFTS_NEEDED"
        if (
            not created
            and not reused
        )
        else "DRAFT_READY"
    )

    return {
        "status": status,
        "origin_date": (
            resolved_origin.isoformat()
        ),
        "created_count": len(
            created
        ),
        "reused_count": len(
            reused
        ),
        "skipped_official_count": len(
            skipped_official
        ),
        "created": created,
        "reused": reused,
        "skipped_official": (
            skipped_official
        ),
    }


def official_confirmation_plan(
    *,
    origin_date: date | None = None,
) -> dict:
    engine = create_sql_engine()

    with engine.connect() as conn:
        repo = ForecastRepository(
            conn
        )

        (
            resolved_origin,
            _,
        ) = _resolve_origin_date(
            repo,
            origin_date,
        )

        drafts = repo.list_open_drafts(
            origin_date=(
                resolved_origin
            )
        )

    return {
        "status": (
            "NO_DRAFTS"
            if not drafts
            else "CONFIRMATION_REQUIRED"
        ),
        "origin_date": (
            resolved_origin.isoformat()
        ),
        "confirmation_phrase": (
            OFFICIAL_CONFIRMATION_PHRASE
        ),
        "draft_count": len(
            drafts
        ),
        "drafts": drafts,
    }


def confirm_officials(
    *,
    confirmation: str | None,
    origin_date: date | None = None,
    confirmed_by: str = "manual",
) -> dict:
    plan = official_confirmation_plan(
        origin_date=origin_date
    )

    if plan["status"] == "NO_DRAFTS":
        return plan

    if (
        confirmation
        != OFFICIAL_CONFIRMATION_PHRASE
    ):
        return plan

    engine = create_sql_engine()

    results: list[dict] = []

    draft_ids = [
        row["draft_id"]
        for row in plan["drafts"]
    ]

    for draft_id in draft_ids:
        with engine.begin() as conn:
            repo = ForecastRepository(
                conn
            )

            draft = repo.draft_for_update(
                draft_id
            )

            if draft is None:
                raise RuntimeError(
                    f"Draft disappeared: {draft_id}"
                )

            existing = (
                repo.official_by_source_draft(
                    draft_id
                )
            )

            if existing is not None:
                results.append(
                    {
                        "status": (
                            "ALREADY_OFFICIAL"
                        ),
                        "draft_id": (
                            draft_id
                        ),
                        "official_id": (
                            existing[
                                "official_id"
                            ]
                        ),
                    }
                )
                continue

            if draft["status"] != "DRAFT":
                raise RuntimeError(
                    f"Draft {draft_id} is not open; "
                    f"status={draft['status']}"
                )

            key_official = repo.official_for_key(
                origin_date=(
                    draft["origin_date"]
                ),
                department_id=(
                    int(
                        draft[
                            "department_id"
                        ]
                    )
                ),
                horizon=int(
                    draft["horizon"]
                ),
            )

            if key_official is not None:
                raise RuntimeError(
                    "Official business key already exists for "
                    f"origin={draft['origin_date']}, "
                    f"department={draft['department_id']}, "
                    f"horizon={draft['horizon']}"
                )

            lock_candidate = (
                repo.daily_lock_candidate_id(
                    origin_date=(
                        draft["origin_date"]
                    ),
                    horizon=int(
                        draft["horizon"]
                    ),
                    for_update=True,
                )
            )

            if lock_candidate is None:
                repo.insert_daily_lock(
                    origin_date=(
                        draft["origin_date"]
                    ),
                    horizon=int(
                        draft["horizon"]
                    ),
                    candidate_id=(
                        draft["candidate_id"]
                    ),
                    trigger_department_id=int(
                        draft[
                            "department_id"
                        ]
                    ),
                )

                lock_candidate = (
                    draft["candidate_id"]
                )

            if (
                lock_candidate
                != draft["candidate_id"]
            ):
                raise RuntimeError(
                    "STALE_DRAFT_MODEL_LOCK_MISMATCH: "
                    f"daily lock uses {lock_candidate} but "
                    f"draft uses {draft['candidate_id']}"
                )

            official_id = _new_id(
                "OFF"
            )

            repo.insert_official(
                official_id=(
                    official_id
                ),
                draft=draft,
                confirmed_by=(
                    confirmed_by
                ),
            )

            repo.mark_draft_confirmed(
                draft_id
            )

            results.append(
                {
                    "status": "OFFICIAL",
                    "official_id": (
                        official_id
                    ),
                    "draft_id": draft_id,
                    "origin_date": str(
                        draft[
                            "origin_date"
                        ]
                    ),
                    "department_id": int(
                        draft[
                            "department_id"
                        ]
                    ),
                    "horizon": int(
                        draft["horizon"]
                    ),
                    "candidate_id": (
                        draft["candidate_id"]
                    ),
                    "prediction_raw": float(
                        draft[
                            "prediction_raw"
                        ]
                    ),
                    "prediction_rounded": int(
                        draft[
                            "prediction_rounded"
                        ]
                    ),
                }
            )

    return {
        "status": "COMPLETED",
        "origin_date": plan[
            "origin_date"
        ],
        "official_count": sum(
            1
            for row in results
            if row["status"]
            == "OFFICIAL"
        ),
        "results": results,
    }