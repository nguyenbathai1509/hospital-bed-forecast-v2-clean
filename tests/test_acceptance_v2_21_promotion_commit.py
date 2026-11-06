from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import src.promotion.service as promotion_service


BUSINESS_DATE = date(2026, 6, 30)
NEXT_DATE = BUSINESS_DATE + timedelta(days=1)

HORIZON = 1

OLD_CANDIDATE = "TRN_OLD_H1_RF"
NEW_CANDIDATE = "TRN_NEW_H1_SVR"

CHANGE_ID = "PROMOTE_ACCEPTANCE_TEST"


class _PlanItem:
    def __init__(
        self,
        *,
        effect,
        effective_from,
    ):
        self.horizon = HORIZON

        self.from_candidate_id = (
            OLD_CANDIDATE
        )

        self.to_candidate_id = (
            NEW_CANDIDATE
        )

        self.effect = effect

        self.effective_from_business_date = (
            effective_from
        )

    def as_dict(self):
        return {
            "horizon": self.horizon,
            "from_candidate_id": (
                self.from_candidate_id
            ),
            "to_candidate_id": (
                self.to_candidate_id
            ),
            "effect": self.effect,
            "effective_from_business_date": (
                self
                .effective_from_business_date
                .isoformat()
            ),
        }


class _Plan:
    def __init__(
        self,
        item,
    ):
        self.business_date = BUSINESS_DATE
        self.quota_used = False
        self.items = (item,)
        self.has_changes = True

    def as_dict(self):
        return {
            "business_date": (
                self.business_date.isoformat()
            ),
            "items": [
                item.as_dict()
                for item in self.items
            ],
        }


class _FakeRepository:
    lock_present = False

    active_candidate = (
        OLD_CANDIDATE
    )

    scheduled_candidate = None

    writes = []

    @classmethod
    def reset(
        cls,
        *,
        lock_present,
    ):
        cls.lock_present = (
            lock_present
        )

        cls.active_candidate = (
            OLD_CANDIDATE
        )

        cls.scheduled_candidate = None
        cls.writes = []

    @classmethod
    def snapshot(cls):
        return {
            "lock_present": (
                cls.lock_present
            ),
            "active_candidate": (
                cls.active_candidate
            ),
            "scheduled_candidate": (
                cls.scheduled_candidate
            ),
            "writes": deepcopy(
                cls.writes
            ),
        }

    @classmethod
    def restore(
        cls,
        state,
    ):
        cls.lock_present = (
            state["lock_present"]
        )

        cls.active_candidate = (
            state["active_candidate"]
        )

        cls.scheduled_candidate = (
            state["scheduled_candidate"]
        )

        cls.writes = deepcopy(
            state["writes"]
        )

    def __init__(
        self,
        conn,
    ):
        self.conn = conn

    def latest_data_ready_business_date(
        self,
    ):
        return BUSINESS_DATE

    def normal_change_exists(
        self,
        business_date,
    ):
        assert (
            business_date
            == BUSINESS_DATE
        )

        return False

    def insert_change_header(
        self,
        **kwargs,
    ):
        self.__class__.writes.append(
            (
                "insert_change_header",
                deepcopy(kwargs),
            )
        )

    def active_production(
        self,
        horizon,
    ):
        assert horizon == HORIZON

        if (
            self.__class__.active_candidate
            is None
        ):
            return None

        return SimpleNamespace(
            candidate_id=(
                self.__class__
                .active_candidate
            )
        )

    def latest_recommended_candidate(
        self,
        horizon,
    ):
        assert horizon == HORIZON

        candidate = SimpleNamespace(
            candidate_id=NEW_CANDIDATE
        )

        meta = {
            "recommendation_id": (
                "REC_ACCEPTANCE"
            ),
            "action": "PROMOTE",
        }

        return candidate, meta

    def daily_lock_exists(
        self,
        business_date,
        horizon,
    ):
        assert (
            business_date
            == BUSINESS_DATE
        )

        assert horizon == HORIZON

        return (
            self.__class__.lock_present
        )

    def insert_change_item(
        self,
        **kwargs,
    ):
        self.__class__.writes.append(
            (
                "insert_change_item",
                deepcopy(kwargs),
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
        assert horizon == HORIZON

        assert (
            business_date
            == BUSINESS_DATE
        )

        self.__class__.active_candidate = (
            candidate_id
        )

        self.__class__.scheduled_candidate = (
            None
        )

        self.__class__.writes.append(
            (
                "activate_candidate",
                candidate_id,
            )
        )

    def schedule_candidate(
        self,
        *,
        horizon,
        candidate_id,
        effective_from_business_date,
        requested_by,
        reason,
    ):
        assert horizon == HORIZON

        self.__class__.scheduled_candidate = (
            candidate_id
        )

        self.__class__.writes.append(
            (
                "schedule_candidate",
                candidate_id,
                effective_from_business_date,
            )
        )


class _Transaction:
    def __enter__(
        self,
    ):
        self.before = (
            _FakeRepository.snapshot()
        )

        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        # Mô phỏng rollback của engine.begin()
        # nếu service phát sinh exception.
        if exc_type is not None:
            _FakeRepository.restore(
                self.before
            )

        return False


class _FakeEngine:
    def begin(
        self,
    ):
        return _Transaction()


def _patch(
    monkeypatch,
    *,
    item,
):
    monkeypatch.setattr(
        promotion_service,
        "plan_promotion",
        lambda horizons: _Plan(
            item
        ),
    )

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
        lambda prefix: CHANGE_ID,
    )


def test_promotion_without_daily_lock_is_immediate(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=False
    )

    item = _PlanItem(
        effect="IMMEDIATE",
        effective_from=BUSINESS_DATE,
    )

    _patch(
        monkeypatch,
        item=item,
    )

    result = (
        promotion_service
        .execute_promotion(
            horizons=(1,),
            confirmation=(
                promotion_service
                .PROMOTION_CONFIRMATION_PHRASE
            ),
            requested_by="acceptance",
            reason="Acceptance immediate",
        )
    )

    assert (
        result["status"]
        == "COMPLETED"
    )

    assert (
        _FakeRepository.active_candidate
        == NEW_CANDIDATE
    )

    assert (
        _FakeRepository.scheduled_candidate
        is None
    )

    names = [
        row[0]
        for row in _FakeRepository.writes
    ]

    assert names == [
        "insert_change_header",
        "insert_change_item",
        "activate_candidate",
    ]

    change_item = (
        _FakeRepository.writes[1][1]
    )

    assert (
        change_item["effect"]
        == "IMMEDIATE"
    )

    assert (
        change_item[
            "effective_from_business_date"
        ]
        == BUSINESS_DATE
    )

    assert (
        change_item["applied_now"]
        is True
    )


def test_promotion_with_daily_lock_is_next_cycle(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=True
    )

    item = _PlanItem(
        effect="NEXT_CYCLE",
        effective_from=NEXT_DATE,
    )

    _patch(
        monkeypatch,
        item=item,
    )

    result = (
        promotion_service
        .execute_promotion(
            horizons=(1,),
            confirmation=(
                promotion_service
                .PROMOTION_CONFIRMATION_PHRASE
            ),
            requested_by="acceptance",
            reason="Acceptance next cycle",
        )
    )

    assert (
        result["status"]
        == "COMPLETED"
    )

    # ACTIVE cũ không được thay ngay.
    assert (
        _FakeRepository.active_candidate
        == OLD_CANDIDATE
    )

    assert (
        _FakeRepository.scheduled_candidate
        == NEW_CANDIDATE
    )

    names = [
        row[0]
        for row in _FakeRepository.writes
    ]

    assert names == [
        "insert_change_header",
        "insert_change_item",
        "schedule_candidate",
    ]

    change_item = (
        _FakeRepository.writes[1][1]
    )

    assert (
        change_item["effect"]
        == "NEXT_CYCLE"
    )

    assert (
        change_item[
            "effective_from_business_date"
        ]
        == NEXT_DATE
    )

    assert (
        change_item["applied_now"]
        is False
    )


def test_promotion_blocks_commit_if_lock_state_changed_after_preview(
    monkeypatch,
):
    # Preview/plan nói rằng đã có lock
    # nên effect là NEXT_CYCLE.
    item = _PlanItem(
        effect="NEXT_CYCLE",
        effective_from=NEXT_DATE,
    )

    # Nhưng tại transaction commit,
    # lock đã biến mất.
    _FakeRepository.reset(
        lock_present=False
    )

    _patch(
        monkeypatch,
        item=item,
    )

    before = (
        _FakeRepository.snapshot()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Official/daily lock state "
            "changed"
        ),
    ):
        (
            promotion_service
            .execute_promotion(
                horizons=(1,),
                confirmation=(
                    promotion_service
                    .PROMOTION_CONFIRMATION_PHRASE
                ),
                requested_by="acceptance",
                reason="Acceptance stale plan",
            )
        )

    # engine.begin() phải rollback toàn bộ.
    assert (
        _FakeRepository.snapshot()
        == before
    )

    assert (
        _FakeRepository.active_candidate
        == OLD_CANDIDATE
    )

    assert (
        _FakeRepository.scheduled_candidate
        is None
    )

    assert (
        _FakeRepository.writes
        == []
    )
