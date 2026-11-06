from __future__ import annotations

from datetime import date

import pytest

from src.promotion import service as promotion_service
from src.promotion.contracts import ProductionCandidate


BUSINESS_DATE = date(2026, 6, 30)

RUN_ID = "TRN_CURRENT"

REC_H1 = ProductionCandidate(
    candidate_id=f"{RUN_ID}_H1_RF",
    horizon=1,
    model_family="RF",
    mae=2.25,
    run_id=RUN_ID,
    registry_status="RECOMMENDED",
    is_recommended=True,
)

ALT_H1 = ProductionCandidate(
    candidate_id=f"{RUN_ID}_H1_SVR",
    horizon=1,
    model_family="SVR",
    mae=2.30,
    run_id=RUN_ID,
    registry_status="CANDIDATE",
    is_recommended=False,
)

ALT_H3 = ProductionCandidate(
    candidate_id=f"{RUN_ID}_H3_SVR",
    horizon=3,
    model_family="SVR",
    mae=2.20,
    run_id=RUN_ID,
    registry_status="CANDIDATE",
    is_recommended=False,
)

OLD_RUN_H1 = ProductionCandidate(
    candidate_id="TRN_OLD_H1_SVR",
    horizon=1,
    model_family="SVR",
    mae=2.10,
    run_id="TRN_OLD",
    registry_status="CANDIDATE",
    is_recommended=False,
)


class _FakeConnection:
    pass


class _Context:
    def __enter__(self):
        return _FakeConnection()

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False


class _FakeEngine:
    def connect(self):
        return _Context()

    def begin(self):
        return _Context()


class _FakeRepository:
    active_candidate_id = None
    writes = []

    candidates = {
        REC_H1.candidate_id: REC_H1,
        ALT_H1.candidate_id: ALT_H1,
        ALT_H3.candidate_id: ALT_H3,
        OLD_RUN_H1.candidate_id: OLD_RUN_H1,
    }

    def __init__(self, conn):
        self.conn = conn

    @classmethod
    def reset(cls):
        cls.active_candidate_id = None
        cls.writes = []

    def latest_data_ready_business_date(self):
        return BUSINESS_DATE

    def latest_recommended_candidate(
        self,
        horizon,
    ):
        if int(horizon) != 1:
            return None

        return (
            REC_H1,
            {
                "recommendation_id": "REC_CURRENT_H1",
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
        if self.active_candidate_id is None:
            return None

        candidate = self.candidates[
            self.active_candidate_id
        ]

        if candidate.horizon != int(horizon):
            return None

        return candidate

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
        return False

    def insert_change_header(
        self,
        **kwargs,
    ):
        self.writes.append(
            (
                "header",
                kwargs,
            )
        )

    def insert_change_item(
        self,
        **kwargs,
    ):
        self.writes.append(
            (
                "item",
                kwargs,
            )
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
        candidate = self.get_candidate(
            candidate_id
        )

        assert candidate is not None
        assert candidate.horizon == int(horizon)

        type(self).active_candidate_id = (
            candidate_id
        )

        self.writes.append(
            (
                "activate",
                {
                    "horizon": horizon,
                    "candidate_id": candidate_id,
                },
            )
        )

    def schedule_candidate(
        self,
        **kwargs,
    ):
        raise AssertionError(
            "Không được schedule trong test "
            "không có Daily Model Lock."
        )


@pytest.fixture(autouse=True)
def _patch_runtime(
    monkeypatch,
):
    _FakeRepository.reset()

    monkeypatch.setattr(
        promotion_service,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )

    monkeypatch.setattr(
        promotion_service,
        "ProductionRepository",
        _FakeRepository,
    )

    monkeypatch.setattr(
        promotion_service,
        "_new_change_id",
        lambda prefix: "PROMOTE_MANUAL_OVERRIDE_TEST",
    )


def test_default_still_uses_recommended_candidate():
    plan = promotion_service.plan_promotion(
        horizons=(1,),
    )

    assert len(plan.items) == 1

    item = plan.items[0]

    assert (
        item.to_candidate_id
        == REC_H1.candidate_id
    )

    assert item.to_model_family == "RF"


def test_manual_override_preview_uses_selected_candidate():
    result = promotion_service.execute_promotion(
        horizons=(1,),
        candidate_ids={
            "1": ALT_H1.candidate_id,
        },
        confirmation=None,
        requested_by="test",
        reason="Manual override preview test",
    )

    assert (
        result["status"]
        == "CONFIRMATION_REQUIRED"
    )

    item = result["plan"]["items"][0]

    assert (
        item["to_candidate_id"]
        == ALT_H1.candidate_id
    )

    assert (
        item["to_model_family"]
        == "SVR"
    )

    # Recommendation vẫn được giữ để audit,
    # nhưng không ép target phải là Recommended.
    assert (
        item["recommendation_id"]
        == "REC_CURRENT_H1"
    )


def test_manual_override_commit_activates_selected_candidate():
    result = promotion_service.execute_promotion(
        horizons=(1,),
        candidate_ids={
            "1": ALT_H1.candidate_id,
        },
        confirmation=(
            promotion_service
            .PROMOTION_CONFIRMATION_PHRASE
        ),
        requested_by="test",
        reason="Manual override commit test",
    )

    assert result["status"] == "COMPLETED"

    assert (
        result["items"][0][
            "to_candidate_id"
        ]
        == ALT_H1.candidate_id
    )

    assert (
        _FakeRepository.active_candidate_id
        == ALT_H1.candidate_id
    )

    assert any(
        kind == "activate"
        and payload["candidate_id"]
        == ALT_H1.candidate_id
        for kind, payload
        in _FakeRepository.writes
    )


def test_manual_override_rejects_wrong_horizon():
    with pytest.raises(
        ValueError,
        match="belongs to H\\+3, not H\\+1",
    ):
        promotion_service.plan_promotion(
            horizons=(1,),
            candidate_ids={
                "1": ALT_H3.candidate_id,
            },
        )


def test_manual_override_rejects_old_training_run():
    with pytest.raises(
        ValueError,
        match=(
            "not from the latest comparable "
            "Training Run"
        ),
    ):
        promotion_service.plan_promotion(
            horizons=(1,),
            candidate_ids={
                "1": OLD_RUN_H1.candidate_id,
            },
        )
