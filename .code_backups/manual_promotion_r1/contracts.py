from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PipelineStatus = Literal[
    "RUNNING",
    "FAILED",
    "BOOTSTRAP_COMPLETED",
    "WAITING",
    "COMPLETED",
    "DATA_READY",
]
QualitySeverity = Literal["ERROR", "WARNING", "CHECK"]
TrainingJobStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
TrainingRunStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
ModelFamily = Literal["RF", "XGBOOST", "SVR", "LSTM"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["OK"] = "OK"
    service: str = "hospital-bed-forecast-v2"
    api_version: str = "v2"


class QualitySummary(StrictModel):
    ERROR: int = Field(ge=0)
    WARNING: int = Field(ge=0)
    CHECK: int = Field(ge=0)


class DataStatusResponse(StrictModel):
    status: Literal["DATA_READY", "NO_DATA_READY"]
    pipeline_run_id: str | None = None
    business_date: date | None = None
    latest_actual_date: date | None = None
    source_mode: str | None = None
    data_version: str | None = None
    rows_extracted: int | None = Field(default=None, ge=0)
    quality: QualitySummary
    active_department_count: int = Field(ge=0)
    completed_at: datetime | None = None


class DepartmentResponse(StrictModel):
    department_id: int
    department_code: str
    department_name: str
    planned_beds: int = Field(gt=0)
    is_active: bool


class PipelineRunSummary(StrictModel):
    run_id: str
    business_date: date | None = None
    source_mode: str
    data_version: str | None = None
    status: PipelineStatus
    started_at: datetime
    completed_at: datetime | None = None
    rows_extracted: int | None = Field(default=None, ge=0)
    quality: QualitySummary
    error_message: str | None = None


class PipelineRunsResponse(StrictModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[PipelineRunSummary]


class PipelineTriggerRequest(StrictModel):
    source_mode: Literal["EXCEL_BOOTSTRAP"] = "EXCEL_BOOTSTRAP"


class PipelineTriggerResponse(StrictModel):
    run_id: str
    status: Literal["DATA_READY", "FAILED", "WAITING"]
    business_date: date | None = None
    data_version: str | None = None
    feature_version: str | None = None
    rows: int | None = Field(default=None, ge=0)
    quality: QualitySummary | None = None
    readiness: dict[str, Any] | None = None
    stages: dict[str, Any]
    error: str | None = None


class DataQualityIssueResponse(StrictModel):
    issue_id: int
    pipeline_run_id: str
    business_date: date | None = None
    department_id: int | None = None
    rule_id: str
    severity: QualitySeverity
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    difference_value: float | None = None
    message: str
    detected_at: datetime
    is_resolved: bool


class DataQualityResponse(StrictModel):
    pipeline_run_id: str | None = None
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[DataQualityIssueResponse]


class HistoryRow(StrictModel):
    business_date: date
    department_id: int
    department_code: str
    department_name: str
    planned_beds: int = Field(gt=0)
    occupied_start: int = Field(ge=0)
    admissions: int = Field(ge=0)
    transfer_in: int = Field(ge=0)
    discharges: int = Field(ge=0)
    transfer_out: int = Field(ge=0)
    occupied_end: int = Field(ge=0)
    occupied_beds: int = Field(ge=0)
    net_flow: int
    occupancy_rate_pct: float
    quality_flag: Literal["PASS", "WARNING", "CHECK"]
    source_revision_no: int = Field(ge=1)


class HistoryResponse(StrictModel):
    department_id: int
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    start_date: date | None = None
    end_date: date | None = None
    rows: list[HistoryRow]


# ---------------------------------------------------------------------------
# V2-19 Part C1 - asynchronous Training API contracts
# ---------------------------------------------------------------------------


class TrainingStartRequest(StrictModel):
    requested_by: str = Field(default="api", min_length=1, max_length=100)
    random_seed: int = Field(default=42, ge=0)


class TrainingStartResponse(StrictModel):
    job_id: str
    status: TrainingJobStatus
    business_date: date
    source_pipeline_run_id: str
    training_run_id: str | None = None
    reused: bool


class TrainingJobStatusResponse(StrictModel):
    job_id: str
    business_date: date
    source_pipeline_run_id: str
    status: TrainingJobStatus
    requested_by: str
    random_seed: int = Field(ge=0)
    training_run_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class TrainingRunSummary(StrictModel):
    run_id: str
    business_date: date
    status: TrainingRunStatus
    triggered_by: str | None = None
    scope: str
    data_start: date | None = None
    data_end: date | None = None
    data_version: str | None = None
    feature_version: str
    row_count: int | None = Field(default=None, ge=0)
    department_count: int | None = Field(default=None, ge=0)
    random_seed: int | None = Field(default=None, ge=0)
    training_contract_version: str | None = None
    completed_candidate_count: int | None = Field(default=None, ge=0)
    started_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class TrainingRunsResponse(StrictModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[TrainingRunSummary]


class CandidateMetricResponse(StrictModel):
    candidate_id: str
    run_id: str
    horizon: Literal[1, 3]
    model_family: ModelFamily
    registry_status: str
    is_recommended: bool
    artifact_type: str
    inference_type: str
    feature_version: str
    data_version: str | None = None
    mae: float
    rmse: float
    wape: float
    r2: float | None = None
    bias: float
    p90_abs_error: float | None = None
    max_abs_error: float
    within_2_rate: float | None = None
    underprediction_rate: float | None = None
    underprediction_mae: float | None = None
    created_at: datetime


class DepartmentMetricResponse(StrictModel):
    candidate_id: str
    department_id: int
    sample_count: int = Field(gt=0)
    mae: float
    rmse: float
    wape: float
    r2: float | None = None
    bias: float
    p90_abs_error: float | None = None
    max_abs_error: float
    within_2_rate: float | None = None
    underprediction_rate: float | None = None
    underprediction_mae: float | None = None


class RecommendationSnapshotResponse(StrictModel):
    recommendation_id: str
    run_id: str
    horizon: Literal[1, 3]
    best_candidate_id: str
    champion_candidate_id: str
    recommended_candidate_id: str
    champion_source: Literal["PRODUCTION", "BOOTSTRAP_REFERENCE"]
    action: Literal["PROMOTE", "KEEP"]
    improvement_pct: float
    minimum_improvement_pct: float
    guardrail_pass: bool
    reason_code: str
    reasons: list[Any]
    guardrails: list[Any]
    policy: dict[str, Any]
    created_at: datetime


class RankingSnapshotResponse(StrictModel):
    recommendation_id: str
    candidate_id: str
    horizon: Literal[1, 3]
    rank_no: int = Field(ge=1)
    is_best_candidate: bool
    mae: float
    rmse: float
    wape: float
    r2: float | None = None
    bias: float
    p90_abs_error: float | None = None
    max_abs_error: float
    within_2_rate: float | None = None
    underprediction_rate: float | None = None
    underprediction_mae: float | None = None


class TrainingResultsResponse(StrictModel):
    run: TrainingRunSummary
    candidates: list[CandidateMetricResponse]
    department_metrics: list[DepartmentMetricResponse]
    recommendations: list[RecommendationSnapshotResponse]
    rankings: list[RankingSnapshotResponse]


# ---------------------------------------------------------------------------
# V2-20B - read-only Training evaluation evidence for visualizations
# ---------------------------------------------------------------------------


class EvaluationSplitResponse(StrictModel):
    train_start: date | None = None
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date


class EvaluationPredictionResponse(StrictModel):
    candidate_id: str
    run_id: str
    horizon: Literal[1, 3]
    model_family: ModelFamily
    department_id: int
    origin_date: date
    target_date: date
    actual_occupied_beds: float
    prediction_raw: float
    residual: float
    absolute_error: float


class TrainingEvaluationResponse(StrictModel):
    run_id: str
    horizon: Literal[1, 3]
    model_family: ModelFamily
    department_id: int | None = None
    split: EvaluationSplitResponse
    count: int = Field(ge=0)
    rows: list[EvaluationPredictionResponse]


# ---------------------------------------------------------------------------
# V2-19 Part C2 - Model Registry / Production / Promotion / Rollback API
# ---------------------------------------------------------------------------


ModelRegistryStatus = Literal[
    "CANDIDATE",
    "RECOMMENDED",
    "PRODUCTION",
    "SCHEDULED",
    "ARCHIVED",
    "FAILED",
]
ProductionSlotStatus = Literal["ACTIVE", "SCHEDULED", "RETIRED"]
ProductionEffect = Literal["IMMEDIATE", "NEXT_CYCLE"]
ModelChangeStatus = Literal["NO_CHANGE", "CONFIRMATION_REQUIRED", "COMPLETED"]


class ModelRegistryItemResponse(StrictModel):
    candidate_id: str
    run_id: str
    horizon: Literal[1, 3]
    model_family: ModelFamily
    scope: str
    registry_status: ModelRegistryStatus
    is_recommended: bool
    artifact_type: str
    inference_type: str
    feature_version: str
    data_version: str | None = None
    mae: float | None = None
    rmse: float | None = None
    wape: float | None = None
    r2: float | None = None
    bias: float | None = None
    p90_abs_error: float | None = None
    max_abs_error: float | None = None
    within_2_rate: float | None = None
    underprediction_rate: float | None = None
    underprediction_mae: float | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ModelsResponse(StrictModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[ModelRegistryItemResponse]


class ProductionSlotResponse(StrictModel):
    production_id: int
    horizon: Literal[1, 3]
    candidate_id: str
    model_family: ModelFamily
    slot_status: ProductionSlotStatus
    registry_status: ModelRegistryStatus
    is_recommended: bool
    mae: float | None = None
    effective_from_business_date: date
    effective_to_business_date: date | None = None
    promoted_by: str | None = None
    promotion_reason: str | None = None
    created_at: datetime


class DailyModelLockResponse(StrictModel):
    origin_date: date
    horizon: Literal[1, 3]
    model_candidate_id: str
    model_family: ModelFamily
    trigger_department_id: int
    locked_at: datetime


class ProductionRecommendationResponse(StrictModel):
    recommendation_id: str
    horizon: Literal[1, 3]
    recommended_candidate_id: str
    recommended_family: ModelFamily
    action: Literal["PROMOTE", "KEEP"]
    guardrail_pass: bool
    created_at: datetime


class ProductionHorizonStateResponse(StrictModel):
    horizon: Literal[1, 3]
    active: ProductionSlotResponse | None = None
    scheduled: ProductionSlotResponse | None = None
    daily_lock: DailyModelLockResponse | None = None
    recommendation: ProductionRecommendationResponse | None = None


class ProductionModelsResponse(StrictModel):
    business_date: date | None = None
    normal_change_quota_used: bool
    horizons: list[ProductionHorizonStateResponse]


class PromotionRequest(StrictModel):
    horizons: list[Literal[1, 3]] = Field(
        default_factory=lambda: [1, 3],
        min_length=1,
        max_length=2,
    )
    confirmation: str | None = Field(default=None, max_length=100)
    requested_by: str = Field(default="api", min_length=1, max_length=100)
    reason: str = Field(
        default="Promote recommended model(s) to Production.",
        max_length=1000,
    )


class RollbackRequest(StrictModel):
    horizon: Literal[1, 3]
    confirmation: str | None = Field(default=None, max_length=100)
    requested_by: str = Field(default="api", min_length=1, max_length=100)
    reason: str = Field(default="", max_length=1000)


class ModelChangePlanItemResponse(StrictModel):
    horizon: Literal[1, 3]
    from_candidate_id: str | None = None
    from_model_family: ModelFamily | None = None
    to_candidate_id: str
    to_model_family: ModelFamily
    to_mae: float
    recommendation_id: str | None = None
    recommendation_action: Literal["PROMOTE", "KEEP"] | None = None
    effect: ProductionEffect
    effective_from_business_date: date
    daily_lock_present: bool


class ModelChangePlanResponse(StrictModel):
    business_date: date
    change_kind: Literal["NORMAL_PROMOTION", "EMERGENCY_ROLLBACK"]
    quota_used: bool
    has_changes: bool
    confirmation_phrase: str
    items: list[ModelChangePlanItemResponse]


class ModelChangeResponse(StrictModel):
    status: ModelChangeStatus
    message: str | None = None
    change_id: str | None = None
    business_date: date | None = None
    change_kind: Literal["NORMAL_PROMOTION", "EMERGENCY_ROLLBACK"] | None = None
    items: list[ModelChangePlanItemResponse] = Field(default_factory=list)
    plan: ModelChangePlanResponse | None = None


# ---------------------------------------------------------------------------
# V2-19 Part D - Forecast Lifecycle + Monitoring API
# ---------------------------------------------------------------------------
ForecastPreviewMode = Literal["PRODUCTION", "RECOMMENDED", "CUSTOM"]
ForecastDraftStatus = Literal["DRAFT", "CONFIRMED", "VOID"]
MonitoringStatus = Literal["NO_OFFICIALS", "WAITING_FOR_ACTUAL", "PARTIAL", "COMPLETED"]


class ForecastPredictionResponse(StrictModel):
    origin_date: date
    department_id: int
    horizon: Literal[1, 3]
    target_date: date
    candidate_id: str
    model_family: ModelFamily
    source_mode: ForecastPreviewMode
    feature_version: str
    data_version: str | None = None
    prediction_raw: float
    prediction_rounded: int = Field(ge=0)
    planned_beds: int = Field(gt=0)
    predicted_utilization_pct: float
    capacity_alert: bool
    capacity_excess_beds: int = Field(ge=0)


class ForecastPreviewRequest(StrictModel):
    mode: ForecastPreviewMode = "PRODUCTION"
    origin_date: date | None = None
    department_ids: list[int] | None = None
    horizons: list[Literal[1, 3]] = Field(default_factory=lambda: [1, 3], min_length=1, max_length=2)
    custom_candidates: dict[str, str] = Field(default_factory=dict)


class ForecastPreviewResponse(StrictModel):
    status: Literal["PREVIEW"]
    persisted: Literal[False]
    official: Literal[False]
    monitoring_eligible: Literal[False]
    mode: ForecastPreviewMode
    origin_date: date
    prediction_count: int = Field(ge=0)
    predictions: list[ForecastPredictionResponse]


class ProductionPredictRequest(StrictModel):
    origin_date: date | None = None
    department_ids: list[int] | None = None
    horizons: list[Literal[1, 3]] = Field(default_factory=lambda: [1, 3], min_length=1, max_length=2)
    created_by: str = Field(default="api", min_length=1, max_length=100)


class ForecastDraftResponse(StrictModel):
    draft_id: str
    origin_date: date
    department_id: int
    horizon: Literal[1, 3]
    target_date: date
    candidate_id: str
    model_family: ModelFamily | None = None
    source_mode: Literal["PRODUCTION"]
    status: ForecastDraftStatus | None = None
    prediction_raw: float
    prediction_rounded: int = Field(ge=0)
    planned_beds: int = Field(gt=0)
    predicted_utilization_pct: float
    capacity_alert: bool
    capacity_excess_beds: int = Field(ge=0)
    feature_version: str
    data_version: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    confirmed_at: datetime | None = None


class SkippedOfficialResponse(StrictModel):
    origin_date: date
    department_id: int
    horizon: Literal[1, 3]
    official_id: str


class ProductionPredictResponse(StrictModel):
    status: Literal["DRAFT_READY", "NO_DRAFTS_NEEDED"]
    origin_date: date
    created_count: int = Field(ge=0)
    reused_count: int = Field(ge=0)
    skipped_official_count: int = Field(ge=0)
    created: list[ForecastDraftResponse]
    reused: list[ForecastDraftResponse]
    skipped_official: list[SkippedOfficialResponse]


class ForecastDraftsResponse(StrictModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[ForecastDraftResponse]


class OfficialConfirmationRequest(StrictModel):
    origin_date: date | None = None
    confirmation: str | None = Field(default=None, max_length=100)
    confirmed_by: str = Field(default="api", min_length=1, max_length=100)


class OfficialConfirmationResult(StrictModel):
    status: str
    draft_id: str | None = None
    official_id: str | None = None
    origin_date: date | None = None
    department_id: int | None = None
    horizon: Literal[1, 3] | None = None
    candidate_id: str | None = None
    prediction_raw: float | None = None
    prediction_rounded: int | None = Field(default=None, ge=0)


class OfficialConfirmationResponse(StrictModel):
    status: str
    origin_date: date
    confirmation_phrase: str | None = None
    draft_count: int | None = Field(default=None, ge=0)
    drafts: list[ForecastDraftResponse] = Field(default_factory=list)
    official_count: int | None = Field(default=None, ge=0)
    results: list[OfficialConfirmationResult] = Field(default_factory=list)


class OfficialForecastResponse(StrictModel):
    official_id: str
    source_draft_id: str
    origin_date: date
    department_id: int
    horizon: Literal[1, 3]
    target_date: date
    candidate_id: str
    model_family: ModelFamily
    prediction_raw: float
    prediction_rounded: int = Field(ge=0)
    planned_beds: int = Field(gt=0)
    predicted_utilization_pct: float
    capacity_alert: bool
    capacity_excess_beds: int = Field(ge=0)
    feature_version: str
    data_version: str | None = None
    confirmed_by: str | None = None
    issued_at: datetime


class OfficialForecastsResponse(StrictModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    rows: list[OfficialForecastResponse]


class MonitoringMetricResponse(StrictModel):
    monitoring_run_id: str | None = None
    metric_scope: Literal["HORIZON", "DEPARTMENT"]
    horizon: Literal[1, 3]
    candidate_id: str
    department_id: int | None = None
    sample_count: int = Field(gt=0)
    through_target_date: date
    mae: float
    rmse: float
    wape: float
    r2: float | None = None
    bias: float
    p90_abs_error: float
    max_abs_error: float
    within_2_rate: float
    underprediction_rate: float
    underprediction_mae: float
    capacity_event_tp: int = Field(ge=0)
    capacity_event_fp: int = Field(ge=0)
    capacity_event_fn: int = Field(ge=0)
    capacity_event_tn: int = Field(ge=0)
    capacity_event_precision: float | None = None
    capacity_event_recall: float | None = None
    capacity_event_accuracy: float


class MonitoringRunSummaryResponse(StrictModel):
    monitoring_run_id: str
    pipeline_run_id: str
    business_date: date
    latest_actual_date: date | None = None
    status: MonitoringStatus
    official_total_count: int = Field(ge=0)
    matched_total_count: int = Field(ge=0)
    waiting_for_actual_count: int = Field(ge=0)
    missing_actual_count: int = Field(ge=0)
    metric_row_count: int = Field(ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MonitoringStatusResponse(StrictModel):
    run: MonitoringRunSummaryResponse | None = None
    metrics: list[MonitoringMetricResponse] = Field(default_factory=list)


class MonitoringRunRequest(StrictModel):
    pipeline_run_id: str | None = Field(default=None, max_length=60)


class MonitoringRunResponse(StrictModel):
    status: MonitoringStatus
    monitoring_run_id: str
    pipeline_run_id: str
    business_date: date
    latest_actual_date: date | None = None
    official_total_count: int = Field(ge=0)
    matched_total_count: int = Field(ge=0)
    waiting_for_actual_count: int = Field(ge=0)
    missing_actual_count: int = Field(ge=0)
    metric_row_count: int = Field(ge=0)
    metrics: list[MonitoringMetricResponse]


class ErrorDetail(StrictModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(StrictModel):
    error: ErrorDetail


# ---------------------------------------------------------------------------
# DEMO-R3 - Demo Reset API contracts
# ---------------------------------------------------------------------------


class DemoResetRequest(StrictModel):
    confirmation: str = Field(
        min_length=1,
        max_length=100,
    )


class DemoResetStatusResponse(StrictModel):
    enabled: bool
    confirmation_phrase: str
    clean: bool
    busy: bool
    busy_counts: dict[str, int]
    counts: dict[str, int]
    retained: dict[str, int]


class DemoResetResponse(StrictModel):
    status: Literal["RESET_COMPLETED"]
    clean: bool
    before: dict[str, int]
    after: dict[str, int]
    retained: dict[str, int]

