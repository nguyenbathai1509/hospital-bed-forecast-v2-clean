from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query, status

from src.api.contracts import (
    DataQualityIssueResponse,
    DataQualityResponse,
    DataStatusResponse,
    ForecastPreviewRequest, ForecastPreviewResponse, ProductionPredictRequest, ProductionPredictResponse,
    ForecastDraftsResponse, ForecastDraftResponse, OfficialConfirmationRequest, OfficialConfirmationResponse,
    OfficialForecastsResponse, OfficialForecastResponse, MonitoringStatusResponse, MonitoringRunRequest, MonitoringRunResponse,
    DepartmentResponse,
    HealthResponse,
    HistoryResponse,
    HistoryRow,
    ModelChangeResponse,
    ModelFamily,
    ModelRegistryItemResponse,
    ModelRegistryStatus,
    ModelsResponse,
    ProductionHorizonStateResponse,
    ProductionModelsResponse,
    ProductionRecommendationResponse,
    ProductionSlotResponse,
    DailyModelLockResponse,
    PromotionRequest,
    RollbackRequest,
    CandidateMetricResponse,
    DepartmentMetricResponse,
    RecommendationSnapshotResponse,
    RankingSnapshotResponse,
    TrainingJobStatusResponse,
    TrainingResultsResponse,
    TrainingRunsResponse,
    TrainingRunStatus,
    TrainingRunSummary,
    TrainingStartRequest,
    TrainingStartResponse,
    PipelineRunsResponse,
    PipelineRunSummary,
    PipelineStatus,
    PipelineTriggerRequest,
    PipelineTriggerResponse,
    QualitySeverity,
    QualitySummary,
)
from src.api.dependencies import (
    PipelineRunner,
    get_pipeline_runner,
    get_read_repository,
    get_training_job_launcher,
    get_training_job_service,
    get_model_command_service,
    get_forecast_command_service,
    get_monitoring_command_service,
)
from src.api.errors import ApiProblem, install_exception_handlers
from src.api.model_commands import ModelCommandService
from src.api.forecast_commands import ForecastCommandService, MonitoringCommandService
from src.api.repository import ApiReadRepository
from src.api.training_jobs import (
    NoDataReadyError,
    TrainingJobLauncher,
    TrainingJobService,
)


API_TITLE = "Hospital Bed Forecast V2 API"
API_VERSION = "2.0.0"


def _quality_from_run(row: dict) -> QualitySummary:
    return QualitySummary(
        ERROR=int(row["quality_error_count"]),
        WARNING=int(row["quality_warning_count"]),
        CHECK=int(row["quality_check_count"]),
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=(
            "Backend API for the V2 hospital-bed forecasting lifecycle. "
            "Business rules remain in existing services; FastAPI is only the "
            "HTTP contract/presentation layer."
        ),
    )

    install_exception_handlers(app)

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="API liveness",
    )
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get(
        "/data/status",
        response_model=DataStatusResponse,
        tags=["data"],
        summary="Latest DATA_READY and quality summary",
    )
    def data_status(
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> DataStatusResponse:
        latest = repo.latest_data_status()
        latest_actual = repo.latest_actual_date()
        department_count = repo.active_department_count()

        if latest is None:
            return DataStatusResponse(
                status="NO_DATA_READY",
                latest_actual_date=latest_actual,
                quality=QualitySummary(
                    ERROR=0,
                    WARNING=0,
                    CHECK=0,
                ),
                active_department_count=department_count,
            )

        return DataStatusResponse(
            status="DATA_READY",
            pipeline_run_id=str(latest["run_id"]),
            business_date=latest["business_date"],
            latest_actual_date=latest_actual,
            source_mode=str(latest["source_mode"]),
            data_version=latest["data_version"],
            rows_extracted=(
                None
                if latest["rows_extracted"] is None
                else int(latest["rows_extracted"])
            ),
            quality=_quality_from_run(latest),
            active_department_count=department_count,
            completed_at=latest["completed_at"],
        )

    @app.get(
        "/departments",
        response_model=list[DepartmentResponse],
        tags=["data"],
        summary="Active departments",
    )
    def departments(
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> list[DepartmentResponse]:
        return [
            DepartmentResponse(
                department_id=int(row["department_id"]),
                department_code=str(row["department_code"]),
                department_name=str(row["department_name"]),
                planned_beds=int(row["planned_beds"]),
                is_active=bool(row["is_active"]),
            )
            for row in repo.departments()
        ]

    @app.get(
        "/pipeline/runs",
        response_model=PipelineRunsResponse,
        tags=["pipeline"],
        summary="Daily Pipeline run history",
    )
    def pipeline_runs(
        status: PipelineStatus | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> PipelineRunsResponse:
        rows = repo.pipeline_runs(
            status=status,
            limit=limit,
            offset=offset,
        )

        return PipelineRunsResponse(
            count=len(rows),
            limit=limit,
            offset=offset,
            rows=[
                PipelineRunSummary(
                    run_id=str(row["run_id"]),
                    business_date=row["business_date"],
                    source_mode=str(row["source_mode"]),
                    data_version=row["data_version"],
                    status=row["status"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    rows_extracted=(
                        None
                        if row["rows_extracted"] is None
                        else int(row["rows_extracted"])
                    ),
                    quality=_quality_from_run(row),
                    error_message=row["error_message"],
                )
                for row in rows
            ],
        )

    @app.post(
        "/pipeline/run",
        response_model=PipelineTriggerResponse,
        tags=["pipeline"],
        summary="Manual Daily Pipeline trigger",
    )
    def pipeline_run(
        request: PipelineTriggerRequest | None = None,
        runner: PipelineRunner = Depends(get_pipeline_runner),
    ) -> PipelineTriggerResponse:
        # The body is optional because the current adapter is fixed. If a body is
        # supplied, source_mode is still strictly validated by Pydantic.
        resolved_request = request or PipelineTriggerRequest()
        _ = resolved_request.source_mode

        try:
            result = runner()
        except Exception as exc:
            raise ApiProblem(
                status_code=500,
                code="PIPELINE_TRIGGER_FAILED",
                message="Daily Pipeline trigger failed unexpectedly.",
                details={
                    "exception_type": type(exc).__name__,
                },
            ) from exc

        quality = result.get("quality")

        return PipelineTriggerResponse(
            run_id=str(result["run_id"]),
            status=result["status"],
            business_date=result.get("business_date"),
            data_version=result.get("data_version"),
            feature_version=result.get("feature_version"),
            rows=result.get("rows"),
            quality=(
                None
                if quality is None
                else QualitySummary(
                    ERROR=int(quality.get("ERROR", 0)),
                    WARNING=int(quality.get("WARNING", 0)),
                    CHECK=int(quality.get("CHECK", 0)),
                )
            ),
            readiness=result.get("readiness"),
            stages=result.get("stages", {}),
            error=result.get("error"),
        )

    @app.get(
        "/data-quality",
        response_model=DataQualityResponse,
        tags=["data"],
        summary="Data Quality issues for a pipeline run",
    )
    def data_quality(
        pipeline_run_id: str | None = None,
        business_date: date | None = None,
        department_id: int | None = Query(default=None, ge=1),
        severity: QualitySeverity | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> DataQualityResponse:
        resolved_run_id = pipeline_run_id or repo.latest_pipeline_run_id()

        if resolved_run_id is None:
            return DataQualityResponse(
                pipeline_run_id=None,
                count=0,
                limit=limit,
                offset=offset,
                rows=[],
            )

        if pipeline_run_id is not None and not repo.pipeline_run_exists(
            pipeline_run_id
        ):
            raise ApiProblem(
                status_code=404,
                code="PIPELINE_RUN_NOT_FOUND",
                message="Pipeline run was not found.",
                details={
                    "pipeline_run_id": pipeline_run_id,
                },
            )

        rows = repo.data_quality_issues(
            pipeline_run_id=resolved_run_id,
            business_date=business_date,
            department_id=department_id,
            severity=severity,
            limit=limit,
            offset=offset,
        )

        return DataQualityResponse(
            pipeline_run_id=resolved_run_id,
            count=len(rows),
            limit=limit,
            offset=offset,
            rows=[
                DataQualityIssueResponse(**row)
                for row in rows
            ],
        )

    @app.get(
        "/history",
        response_model=HistoryResponse,
        tags=["data"],
        summary="CLEAN occupancy and patient-flow history by department",
    )
    def history(
        department_id: int = Query(ge=1),
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = Query(default=366, ge=1, le=2000),
        offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> HistoryResponse:
        if (
            start_date is not None
            and end_date is not None
            and start_date > end_date
        ):
            raise ApiProblem(
                status_code=400,
                code="INVALID_DATE_RANGE",
                message="start_date must be less than or equal to end_date.",
                details={
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            )

        if not repo.department_exists(department_id):
            raise ApiProblem(
                status_code=404,
                code="DEPARTMENT_NOT_FOUND",
                message="Department was not found.",
                details={
                    "department_id": department_id,
                },
            )

        rows = repo.history_rows(
            department_id=department_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

        return HistoryResponse(
            department_id=department_id,
            count=len(rows),
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
            rows=[
                HistoryRow(**row)
                for row in rows
            ],
        )


    @app.post(
        "/training/start",
        response_model=TrainingStartResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["training"],
        summary="Start or reuse an asynchronous Training Job",
    )
    def training_start(
        request: TrainingStartRequest | None = None,
        service: TrainingJobService = Depends(get_training_job_service),
        launcher: TrainingJobLauncher = Depends(get_training_job_launcher),
    ) -> TrainingStartResponse:
        resolved = request or TrainingStartRequest()

        try:
            job = service.start_job(
                requested_by=resolved.requested_by,
                random_seed=resolved.random_seed,
            )
        except NoDataReadyError as exc:
            raise ApiProblem(
                status_code=409,
                code="TRAINING_DATA_NOT_READY",
                message=str(exc),
                details=None,
            ) from exc
        except ValueError as exc:
            raise ApiProblem(
                status_code=400,
                code="TRAINING_START_INVALID",
                message=str(exc),
                details=None,
            ) from exc

        if job["should_schedule"]:
            try:
                launcher.launch(str(job["job_id"]))
            except Exception as exc:
                service.mark_launch_failed(str(job["job_id"]), exc)
                raise ApiProblem(
                    status_code=500,
                    code="TRAINING_WORKER_LAUNCH_FAILED",
                    message="Training Job was created but the worker process could not start.",
                    details={
                        "job_id": str(job["job_id"]),
                        "exception_type": type(exc).__name__,
                    },
                ) from exc

        return TrainingStartResponse(
            job_id=str(job["job_id"]),
            status=job["status"],
            business_date=job["business_date"],
            source_pipeline_run_id=str(job["source_pipeline_run_id"]),
            training_run_id=job.get("training_run_id"),
            reused=bool(job["reused"]),
        )

    @app.get(
        "/training/status/{job_id}",
        response_model=TrainingJobStatusResponse,
        tags=["training"],
        summary="Poll persistent Training Job status",
    )
    def training_status(
        job_id: str,
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> TrainingJobStatusResponse:
        row = repo.training_job(job_id)
        if row is None:
            raise ApiProblem(
                status_code=404,
                code="TRAINING_JOB_NOT_FOUND",
                message="Training Job was not found.",
                details={"job_id": job_id},
            )
        return TrainingJobStatusResponse(**row)

    @app.get(
        "/training/runs",
        response_model=TrainingRunsResponse,
        tags=["training"],
        summary="Training Run history",
    )
    def training_runs(
        status_filter: TrainingRunStatus | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> TrainingRunsResponse:
        rows = repo.training_runs(
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return TrainingRunsResponse(
            count=len(rows),
            limit=limit,
            offset=offset,
            rows=[TrainingRunSummary(**row) for row in rows],
        )

    @app.get(
        "/training/results/{run_id}",
        response_model=TrainingResultsResponse,
        tags=["training"],
        summary="Training metrics, per-department metrics, rankings and recommendation",
    )
    def training_results(
        run_id: str,
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> TrainingResultsResponse:
        run = repo.training_run(run_id)
        if run is None:
            raise ApiProblem(
                status_code=404,
                code="TRAINING_RUN_NOT_FOUND",
                message="Training Run was not found.",
                details={"run_id": run_id},
            )

        return TrainingResultsResponse(
            run=TrainingRunSummary(**run),
            candidates=[
                CandidateMetricResponse(**row)
                for row in repo.candidates_for_training_run(run_id)
            ],
            department_metrics=[
                DepartmentMetricResponse(**row)
                for row in repo.department_metrics_for_training_run(run_id)
            ],
            recommendations=[
                RecommendationSnapshotResponse(**row)
                for row in repo.recommendations_for_training_run(run_id)
            ],
            rankings=[
                RankingSnapshotResponse(**row)
                for row in repo.rankings_for_training_run(run_id)
            ],
        )


    @app.get(
        "/models",
        response_model=ModelsResponse,
        tags=["models"],
        summary="Model Registry candidates",
    )
    def models(
        run_id: str | None = None,
        horizon: int | None = Query(default=None, ge=1, le=3),
        model_family: ModelFamily | None = None,
        registry_status: ModelRegistryStatus | None = None,
        is_recommended: bool | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> ModelsResponse:
        if horizon not in (None, 1, 3):
            raise ApiProblem(
                status_code=400,
                code="MODEL_HORIZON_INVALID",
                message="horizon must be 1 or 3.",
                details={"horizon": horizon},
            )

        rows = repo.model_candidates(
            run_id=run_id,
            horizon=horizon,
            model_family=model_family,
            registry_status=registry_status,
            is_recommended=is_recommended,
            limit=limit,
            offset=offset,
        )

        return ModelsResponse(
            count=len(rows),
            limit=limit,
            offset=offset,
            rows=[ModelRegistryItemResponse(**row) for row in rows],
        )

    @app.get(
        "/models/production",
        response_model=ProductionModelsResponse,
        tags=["models"],
        summary="Current Production, scheduled models, daily locks and recommendation",
    )
    def production_models(
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> ProductionModelsResponse:
        business_date = repo.latest_data_ready_business_date()
        states = []

        for horizon in (1, 3):
            slots = repo.current_production_slots(horizon)
            active_row = next(
                (row for row in slots if row["slot_status"] == "ACTIVE"),
                None,
            )
            scheduled_row = next(
                (row for row in slots if row["slot_status"] == "SCHEDULED"),
                None,
            )
            lock_row = (
                None
                if business_date is None
                else repo.daily_model_lock(business_date, horizon)
            )
            recommendation_row = repo.latest_recommendation_for_horizon(horizon)

            states.append(
                ProductionHorizonStateResponse(
                    horizon=horizon,
                    active=(
                        None
                        if active_row is None
                        else ProductionSlotResponse(**active_row)
                    ),
                    scheduled=(
                        None
                        if scheduled_row is None
                        else ProductionSlotResponse(**scheduled_row)
                    ),
                    daily_lock=(
                        None
                        if lock_row is None
                        else DailyModelLockResponse(**lock_row)
                    ),
                    recommendation=(
                        None
                        if recommendation_row is None
                        else ProductionRecommendationResponse(**recommendation_row)
                    ),
                )
            )

        return ProductionModelsResponse(
            business_date=business_date,
            normal_change_quota_used=repo.normal_production_change_exists(
                business_date
            ),
            horizons=states,
        )

    @app.post(
        "/models/promote",
        response_model=ModelChangeResponse,
        tags=["models"],
        summary="Preview or commit V2-16 Production Promotion",
    )
    def promote_models(
        request: PromotionRequest | None = None,
        service: ModelCommandService = Depends(get_model_command_service),
    ) -> ModelChangeResponse:
        resolved = request or PromotionRequest()

        try:
            result = service.promote(
                horizons=resolved.horizons,
                confirmation=resolved.confirmation,
                requested_by=resolved.requested_by,
                reason=resolved.reason,
            )
        except ValueError as exc:
            raise ApiProblem(
                status_code=400,
                code="MODEL_PROMOTION_INVALID",
                message=str(exc),
                details=None,
            ) from exc
        except RuntimeError as exc:
            raise ApiProblem(
                status_code=409,
                code="MODEL_PROMOTION_CONFLICT",
                message=str(exc),
                details=None,
            ) from exc

        return ModelChangeResponse.model_validate(result)

    @app.post(
        "/models/rollback",
        response_model=ModelChangeResponse,
        tags=["models"],
        summary="Preview or commit audited V2-16 emergency rollback",
    )
    def rollback_model(
        request: RollbackRequest,
        service: ModelCommandService = Depends(get_model_command_service),
    ) -> ModelChangeResponse:
        try:
            result = service.rollback(
                horizon=request.horizon,
                confirmation=request.confirmation,
                requested_by=request.requested_by,
                reason=request.reason,
            )
        except ValueError as exc:
            raise ApiProblem(
                status_code=400,
                code="MODEL_ROLLBACK_INVALID",
                message=str(exc),
                details=None,
            ) from exc
        except RuntimeError as exc:
            raise ApiProblem(
                status_code=409,
                code="MODEL_ROLLBACK_CONFLICT",
                message=str(exc),
                details=None,
            ) from exc

        return ModelChangeResponse.model_validate(result)


    # ------------------------------------------------------------------
    # V2-19 Part D - Forecast Lifecycle + Monitoring API
    # ------------------------------------------------------------------
    @app.post(
        "/forecasts/preview", response_model=ForecastPreviewResponse, tags=["forecasts"],
        summary="Read-only V2-17 forecast Preview",
    )
    def forecast_preview(request: ForecastPreviewRequest, service: ForecastCommandService = Depends(get_forecast_command_service)) -> ForecastPreviewResponse:
        try:
            result = service.preview(
                mode=request.mode, origin_date=request.origin_date, department_ids=request.department_ids,
                horizons=request.horizons, custom_candidates={int(k): v for k, v in request.custom_candidates.items()},
            )
        except ValueError as exc:
            raise ApiProblem(400, "FORECAST_PREVIEW_INVALID", str(exc), None) from exc
        except RuntimeError as exc:
            raise ApiProblem(409, "FORECAST_PREVIEW_CONFLICT", str(exc), None) from exc
        return ForecastPreviewResponse.model_validate(result)

    @app.post(
        "/forecasts/production", response_model=ProductionPredictResponse, tags=["forecasts"],
        summary="Run Production Predict and create/reuse Draft forecasts only",
    )
    def production_predict(request: ProductionPredictRequest | None = None, service: ForecastCommandService = Depends(get_forecast_command_service)) -> ProductionPredictResponse:
        resolved = request or ProductionPredictRequest()
        try:
            result = service.production_predict(
                origin_date=resolved.origin_date, department_ids=resolved.department_ids,
                horizons=resolved.horizons, created_by=resolved.created_by,
            )
        except ValueError as exc:
            raise ApiProblem(400, "FORECAST_PRODUCTION_INVALID", str(exc), None) from exc
        except RuntimeError as exc:
            raise ApiProblem(409, "FORECAST_PRODUCTION_CONFLICT", str(exc), None) from exc
        return ProductionPredictResponse.model_validate(result)

    @app.get(
        "/forecasts/drafts", response_model=ForecastDraftsResponse, tags=["forecasts"],
        summary="List persisted Production Draft forecasts",
    )
    def forecast_drafts(
        origin_date: date | None = None, department_id: int | None = None, horizon: int | None = Query(default=None, ge=1, le=3),
        draft_status: str | None = Query(default=None, alias="status"), limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
        repo: ApiReadRepository = Depends(get_read_repository),
    ) -> ForecastDraftsResponse:
        if horizon not in (None, 1, 3):
            raise ApiProblem(400, "FORECAST_HORIZON_INVALID", "horizon must be 1 or 3", None)
        if draft_status not in (None, "DRAFT", "CONFIRMED", "VOID"):
            raise ApiProblem(400, "FORECAST_DRAFT_STATUS_INVALID", "status must be DRAFT, CONFIRMED or VOID", None)
        rows = repo.forecast_drafts(origin_date=origin_date, department_id=department_id, horizon=horizon, status=draft_status, limit=limit, offset=offset)
        return ForecastDraftsResponse(count=len(rows), limit=limit, offset=offset, rows=[ForecastDraftResponse(**row) for row in rows])

    @app.post(
        "/forecasts/official/confirm", response_model=OfficialConfirmationResponse, tags=["forecasts"],
        summary="Preview or confirm immutable Official forecasts",
    )
    def confirm_official(request: OfficialConfirmationRequest | None = None, service: ForecastCommandService = Depends(get_forecast_command_service)) -> OfficialConfirmationResponse:
        resolved = request or OfficialConfirmationRequest()
        try:
            result = service.confirm_official(confirmation=resolved.confirmation, origin_date=resolved.origin_date, confirmed_by=resolved.confirmed_by)
        except ValueError as exc:
            raise ApiProblem(400, "FORECAST_OFFICIAL_INVALID", str(exc), None) from exc
        except RuntimeError as exc:
            raise ApiProblem(409, "FORECAST_OFFICIAL_CONFLICT", str(exc), None) from exc
        return OfficialConfirmationResponse.model_validate(result)

    @app.get(
        "/forecasts/official", response_model=OfficialForecastsResponse, tags=["forecasts"],
        summary="List immutable Official Forecast audit evidence",
    )
    def official_forecasts(
        origin_date: date | None = None, department_id: int | None = None, horizon: int | None = Query(default=None, ge=1, le=3),
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), repo: ApiReadRepository = Depends(get_read_repository),
    ) -> OfficialForecastsResponse:
        if horizon not in (None, 1, 3):
            raise ApiProblem(400, "FORECAST_HORIZON_INVALID", "horizon must be 1 or 3", None)
        rows = repo.official_forecasts(origin_date=origin_date, department_id=department_id, horizon=horizon, limit=limit, offset=offset)
        return OfficialForecastsResponse(count=len(rows), limit=limit, offset=offset, rows=[OfficialForecastResponse(**row) for row in rows])

    @app.get(
        "/monitoring", response_model=MonitoringStatusResponse, tags=["monitoring"],
        summary="Read latest Official-only Production monitoring snapshot",
    )
    def monitoring_status(repo: ApiReadRepository = Depends(get_read_repository)) -> MonitoringStatusResponse:
        run = repo.latest_monitoring_run()
        if run is None:
            return MonitoringStatusResponse(run=None, metrics=[])
        return MonitoringStatusResponse(run=run, metrics=repo.monitoring_metrics(str(run["monitoring_run_id"])))

    @app.post(
        "/monitoring/run", response_model=MonitoringRunResponse, tags=["monitoring"],
        summary="Run/recover V2-18 Actual Matching + Production Monitoring",
    )
    def run_monitoring(request: MonitoringRunRequest | None = None, service: MonitoringCommandService = Depends(get_monitoring_command_service)) -> MonitoringRunResponse:
        resolved = request or MonitoringRunRequest()
        try:
            result = service.run(pipeline_run_id=resolved.pipeline_run_id)
        except ValueError as exc:
            raise ApiProblem(400, "MONITORING_INVALID", str(exc), None) from exc
        except RuntimeError as exc:
            raise ApiProblem(409, "MONITORING_CONFLICT", str(exc), None) from exc
        return MonitoringRunResponse.model_validate(result)

    return app


app = create_app()