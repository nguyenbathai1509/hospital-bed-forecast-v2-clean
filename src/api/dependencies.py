from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path

from src.api.model_commands import ModelCommandService
from src.api.forecast_commands import ForecastCommandService, MonitoringCommandService
from src.api.repository import ApiReadRepository
from src.api.training_jobs import TrainingJobLauncher, TrainingJobService
from src.forecast.uncertainty_service import UncertaintyService
from src.db.engine import create_sql_engine
from src.demo_reset.service import DemoResetService
from src.services.daily_pipeline_service import run_daily_excel_pipeline


PipelineRunner = Callable[[], dict]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_read_repository() -> Generator[ApiReadRepository, None, None]:
    """Own one short read-only DB connection per request."""

    engine = create_sql_engine()

    with engine.connect() as conn:
        yield ApiReadRepository(conn)


def get_pipeline_runner() -> PipelineRunner:
    """Return the current source-adapter backed manual Daily Pipeline trigger.

    The API does not accept arbitrary host file paths. During EXCEL_BOOTSTRAP it uses
    the project's verified data/HSNoi.xlsx and data/hsNgoai.xlsx locations. A future
    Hospital SQL adapter can replace this dependency without changing the endpoint.
    """

    noi_path = PROJECT_ROOT / "data" / "HSNoi.xlsx"
    ngoai_path = PROJECT_ROOT / "data" / "hsNgoai.xlsx"

    def _run() -> dict:
        return run_daily_excel_pipeline(
            noi_path,
            ngoai_path,
        )

    return _run


def get_training_job_service() -> TrainingJobService:
    """Return the persistent asynchronous Training Job orchestrator.

    The service owns no long-lived database connection. It opens short transactions
    only when start/poll/background execution requires them, so the FastAPI dependency
    is safe to pass to BackgroundTasks after the HTTP response is created.
    """

    return TrainingJobService()


def get_training_job_launcher() -> TrainingJobLauncher:
    return TrainingJobLauncher()


def get_model_command_service() -> ModelCommandService:
    """Return the V2-16 Promotion/Rollback command adapter.

    Authorization is intentionally not implemented here; Roles/Permissions remain a
    later lifecycle gate.  Until then, command endpoints are local/internal only.
    """

    return ModelCommandService()


def get_forecast_command_service() -> ForecastCommandService:
    """Return the V2-17 lifecycle adapter; no Forecast business rules live in FastAPI."""
    return ForecastCommandService()


def get_uncertainty_service() -> UncertaintyService:
    return UncertaintyService()


def get_monitoring_command_service() -> MonitoringCommandService:
    """Return the V2-18 recovery/manual monitoring adapter."""
    return MonitoringCommandService()


def get_demo_reset_service() -> DemoResetService:
    """Return local/internal Demo Reset service.

    Service v?n t? ki?m tra V2_DEMO_RESET_ENABLED v? confirmation phrase.
    """
    return DemoResetService()

