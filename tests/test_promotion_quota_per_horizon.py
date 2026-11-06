from __future__ import annotations

from datetime import date

import pytest

from src.promotion import service as promotion_service
from src.promotion.contracts import ProductionCandidate


BUSINESS_DATE = date(2026, 6, 30)
RUN_ID = "TRN_QUOTA_TEST"

H1_RF = ProductionCandidate(
    candidate_id=f"{RUN_ID}_H1_RF",
    horizon=1,
    model_family="RF",
    mae=2.25,
    run_id=RUN_ID,
    registry_status="RECOMMENDED",
    is_recommended=True,
)

H3_SVR = ProductionCandidate(
    candidate_id=f"{RUN_ID}_H3_SVR",
    horizon=3,
    model_family="SVR",
    mae=2.20,
    run_id=RUN_ID,
    registry_status="RECOMMENDED",
    is_recommended=True,
)


class _Connection:
    pass


class _Context:
    def __enter__(self):
        return _Connection()

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False


class _Engine:
    def connect(self):
        return _Context()

    def begin(self):
        return _Context()


class _Repository:
    active = {}
    writes = []

    quota_used = {
        1: True,
        3: False,
    }

    candidates = {
        H1_RF.candidate_id: H1_RF,
        H3_SVR.candidate_id: H3_SVR,
    }

    def __init__(self, conn):
        self.conn = conn

    @classmethod
    def reset(cls):
        cls.active = {}
        cls.writes = []

    def latest_data_ready_business_date(self):
        return BUSINESS_DATE

    def latest_recommended_candidate(
        self,
        horizon,
    ):
        horizon = int(horizon)

        if horizon == 1:
            candidate = H1_RF
        elif horizon == 3:
            candidate = H3_SVR
        else:
            return None

        return (
            candidate,
            {
                "recommendation_id": (
                    f"REC_{RUN_ID}_H{horizon}"
                ),
                "action": "PROMOTE",
            },
        )

    def get_candidate(
        self,
        candidate_id,
    ):
        return self.candidates.get(
            candidate_id
        )

    def active_production(
        self,
        horizon,
    ):
        candidate_id = self.active.get(
            int(horizon)
        )

        if candidate_id is None:
            return None

        return self.candidates[
            candidate_id
        ]

    def daily_lock_exists(
        self,
        business_date,
        horizon,
    ):
        return False

    def normal_change_exists(
        self,
        business_date,
    ):
        # Legacy/global answer deliberately True.
        # New business logic must prefer per-horizon quota.
        return True

    def normal_change_exists_for_horizon(
        self,
        business_date,
        horizon,
    ):
        return self.quota_used[
            int(horizon)
        ]

    def insert_change_header(
        self,
        **kwargs,
    ):
        self.writes.append(
            ("header", kwargs)
        )

    def insert_change_item(
        self,
        **kwargs,
    ):
        self.writes.append(
            ("item", kwargs)
        )

    def activate_candidate(
        self,
        *,
        horizon,
        candidate_id,
        business_date,
        requested_by,
        reason,
    ):
        type(self).active[
            int(horizon)
        ] = candidate_id

        self.writes.append(
            (
                "activate",
                {
                    "horizon": int(horizon),
                    "candidate_id": candidate_id,
                },
            )
        )

    def schedule_candidate(
        self,
        **kwargs,
    ):
        raise AssertionError(
            "Không được schedule trong test này."
        )


@pytest.fixture(autouse=True)
def _runtime(monkeypatch):
    _Repository.reset()

    monkeypatch.setattr(
        promotion_service,
        "create_sql_engine",
        lambda: _Engine(),
    )

    monkeypatch.setattr(
        promotion_service,
        "ProductionRepository",
        _Repository,
    )

    monkeypatch.setattr(
        promotion_service,
        "_new_change_id",
        lambda prefix: "PROMOTE_HORIZON_QUOTA_TEST",
    )


def test_h1_quota_used_blocks_h1_promotion():
    plan = promotion_service.plan_promotion(
        horizons=(1,),
    )

    assert plan.quota_used is True

    with pytest.raises(
        RuntimeError,
        match=(
            "quota already used"
        ),
    ):
        promotion_service.execute_promotion(
            horizons=(1,),
            confirmation=(
                promotion_service
                .PROMOTION_CONFIRMATION_PHRASE
            ),
            requested_by="test",
            reason="H1 quota must block",
        )


def test_h3_quota_free_allows_h3_promotion():
    plan = promotion_service.plan_promotion(
        horizons=(3,),
    )

    assert plan.quota_used is False

    result = promotion_service.execute_promotion(
        horizons=(3,),
        confirmation=(
            promotion_service
            .PROMOTION_CONFIRMATION_PHRASE
        ),
        requested_by="test",
        reason="H3 independent quota",
    )

    assert result["status"] == "COMPLETED"

    assert (
        _Repository.active[3]
        == H3_SVR.candidate_id
    )

    assert any(
        kind == "activate"
        and payload["horizon"] == 3
        and payload["candidate_id"]
        == H3_SVR.candidate_id
        for kind, payload
        in _Repository.writes
    )


def test_requesting_h1_and_h3_together_blocks_transaction_if_h1_used():
    plan = promotion_service.plan_promotion(
        horizons=(1, 3),
    )

    assert plan.quota_used is True

    with pytest.raises(
        RuntimeError,
        match="quota already used",
    ):
        promotion_service.execute_promotion(
            horizons=(1, 3),
            confirmation=(
                promotion_service
                .PROMOTION_CONFIRMATION_PHRASE
            ),
            requested_by="test",
            reason="Mixed quota must be atomic",
        )

    assert _Repository.active == {}
