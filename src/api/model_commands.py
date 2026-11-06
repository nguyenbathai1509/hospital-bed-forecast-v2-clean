from __future__ import annotations

from src.promotion.service import (
    execute_emergency_rollback,
    execute_promotion,
)


class ModelCommandService:
    """Thin FastAPI command adapter around the verified V2-16 services.

    This class deliberately contains no Promotion/Rollback business rules.  It only
    gives the API layer one dependency that can be replaced in unit tests while the
    real runtime continues to execute the already-verified V2-16 transactions.
    """

    def promote(
        self,
        *,
        horizons,
        confirmation: str | None,
        requested_by: str,
        reason: str,
        candidate_ids: dict[str, str] | None = None,
    ) -> dict:
        # Keep the historical call shape when there is no manual override.
        # This preserves backward compatibility with existing callers/tests.
        if candidate_ids is None:
            return execute_promotion(
                horizons=horizons,
                confirmation=confirmation,
                requested_by=requested_by,
                reason=reason,
            )

        return execute_promotion(
            horizons=horizons,
            candidate_ids=candidate_ids,
            confirmation=confirmation,
            requested_by=requested_by,
            reason=reason,
        )

    def rollback(
        self,
        *,
        horizon: int,
        confirmation: str | None,
        requested_by: str,
        reason: str,
    ) -> dict:
        return execute_emergency_rollback(
            horizon=horizon,
            confirmation=confirmation,
            requested_by=requested_by,
            reason=reason,
        )