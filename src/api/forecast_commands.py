from __future__ import annotations

from src.forecast.service import (
    confirm_officials,
    create_production_drafts,
    generate_preview,
)
from src.monitoring.service import run_monitoring_cycle


class ForecastCommandService:
    """Thin API adapter around the verified V2-17 forecast lifecycle.

    FastAPI must not duplicate Preview/Draft/Official business rules.
    """

    def preview(self, **kwargs) -> dict:
        return generate_preview(**kwargs)

    def production_predict(self, **kwargs) -> dict:
        return create_production_drafts(**kwargs)

    def confirm_official(self, **kwargs) -> dict:
        return confirm_officials(**kwargs)


class MonitoringCommandService:
    """Thin API adapter around verified V2-18 Actual Matching + Monitoring.

    ``run_monitoring_cycle`` returns a wrapper containing both the Actual Matching
    stage and the Production Monitoring stage. The Part D HTTP contract exposes
    only the Production Monitoring snapshot; Actual Matching remains an internal
    lifecycle stage. Unwrap here so FastAPI continues to delegate business logic
    without duplicating it.
    """

    def run(self, *, pipeline_run_id: str | None = None) -> dict:
        cycle = run_monitoring_cycle(
            pipeline_run_id=pipeline_run_id
        )

        monitoring = cycle.get("production_monitoring")
        if not isinstance(monitoring, dict):
            raise RuntimeError(
                "Monitoring cycle did not return a production_monitoring payload"
            )

        return monitoring