from copy import deepcopy
from dataclasses import dataclass
from datetime import date

import pytest

import src.promotion.service as promotion_service


BUSINESS_DATE = date(2026, 6, 30)

CURRENT = "C_CURRENT_RF_H1"
PREVIOUS = "C_PREVIOUS_SVR_H1"

CHANGE_ID = "ROLLBACK_ACCEPTANCE"


@dataclass
class _Candidate:
    candidate_id: str
    model_family: str
    mae: float


class _FakeRepository:
    lock_present = False

    active_candidate = CURRENT
    previous_candidate = PREVIOUS

    scheduled_candidate = None
    scheduled_effective_from = None

    writes = []

    # Đây là state tượng trưng cho dữ liệu
    # đã được phát hành/khóa trước rollback.
    daily_lock_state = {
        "origin_date": BUSINESS_DATE,
        "horizon": 1,
        "model_candidate_id": CURRENT,
    }

    official_state = [
        {
            "official_id": "OFF_001",
            "origin_date": BUSINESS_DATE,
            "horizon": 1,
            "candidate_id": CURRENT,
            "prediction_rounded": 50,
        }
    ]

    mutate_on_begin = None

    def __init__(
        self,
        conn,
    ):
        self.conn = conn

    @classmethod
    def reset(
        cls,
        *,
        lock_present=False,
    ):
        cls.lock_present = lock_present

        cls.active_candidate = CURRENT
        cls.previous_candidate = PREVIOUS

        cls.scheduled_candidate = None
        cls.scheduled_effective_from = None

        cls.writes = []

        cls.daily_lock_state = {
            "origin_date": BUSINESS_DATE,
            "horizon": 1,
            "model_candidate_id": CURRENT,
        }

        cls.official_state = [
            {
                "official_id": "OFF_001",
                "origin_date": BUSINESS_DATE,
                "horizon": 1,
                "candidate_id": CURRENT,
                "prediction_rounded": 50,
            }
        ]

        cls.mutate_on_begin = None

    @classmethod
    def snapshot(
        cls,
    ):
        return {
            "lock_present":
                cls.lock_present,
            "active_candidate":
                cls.active_candidate,
            "previous_candidate":
                cls.previous_candidate,
            "scheduled_candidate":
                cls.scheduled_candidate,
            "scheduled_effective_from":
                cls.scheduled_effective_from,
            "writes":
                deepcopy(
                    cls.writes
                ),
            "daily_lock_state":
                deepcopy(
                    cls.daily_lock_state
                ),
            "official_state":
                deepcopy(
                    cls.official_state
                ),
        }

    @classmethod
    def restore(
        cls,
        snapshot,
    ):
        cls.lock_present = (
            snapshot[
                "lock_present"
            ]
        )

        cls.active_candidate = (
            snapshot[
                "active_candidate"
            ]
        )

        cls.previous_candidate = (
            snapshot[
                "previous_candidate"
            ]
        )

        cls.scheduled_candidate = (
            snapshot[
                "scheduled_candidate"
            ]
        )

        cls.scheduled_effective_from = (
            snapshot[
                "scheduled_effective_from"
            ]
        )

        cls.writes = deepcopy(
            snapshot["writes"]
        )

        cls.daily_lock_state = deepcopy(
            snapshot[
                "daily_lock_state"
            ]
        )

        cls.official_state = deepcopy(
            snapshot[
                "official_state"
            ]
        )

    def latest_data_ready_business_date(
        self,
    ):
        return BUSINESS_DATE

    def active_production(
        self,
        horizon,
    ):
        if (
            horizon != 1
            or self.active_candidate
            is None
        ):
            return None

        return _Candidate(
            candidate_id=(
                self.active_candidate
            ),
            model_family="RF",
            mae=2.0,
        )

    def previous_retired_candidate(
        self,
        horizon,
        current_candidate_id,
    ):
        if (
            horizon != 1
            or self.previous_candidate
            is None
        ):
            return None

        return _Candidate(
            candidate_id=(
                self.previous_candidate
            ),
            model_family="SVR",
            mae=2.2,
        )

    def daily_lock_exists(
        self,
        business_date,
        horizon,
    ):
        return bool(
            self.lock_present
        )

    def normal_change_exists(
        self,
        business_date,
    ):
        # Emergency rollback được phép bypass
        # normal quota.
        return True

    def insert_change_header(
        self,
        **kwargs,
    ):
        self.writes.append(
            (
                "HEADER",
                deepcopy(kwargs),
            )
        )

    def insert_change_item(
        self,
        **kwargs,
    ):
        self.writes.append(
            (
                "ITEM",
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
        self.writes.append(
            (
                "ACTIVATE",
                candidate_id,
            )
        )

        cls = type(self)

        cls.active_candidate = (
            candidate_id
        )

        cls.scheduled_candidate = None
        cls.scheduled_effective_from = None

    def schedule_candidate(
        self,
        *,
        horizon,
        candidate_id,
        effective_from_business_date,
        requested_by,
        reason,
    ):
        self.writes.append(
            (
                "SCHEDULE",
                candidate_id,
                effective_from_business_date,
            )
        )

        cls = type(self)

        cls.scheduled_candidate = (
            candidate_id
        )

        cls.scheduled_effective_from = (
            effective_from_business_date
        )


class _ConnectContext:
    def __enter__(
        self,
    ):
        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class _Transaction:
    def __enter__(
        self,
    ):
        self.before = (
            _FakeRepository.snapshot()
        )

        mutation = (
            _FakeRepository
            .mutate_on_begin
        )

        if mutation == "LOCK_APPEARS":
            _FakeRepository.lock_present = True

        elif mutation == "ACTIVE_CHANGES":
            _FakeRepository.active_candidate = (
                "C_OTHER_ACTIVE"
            )

        elif mutation == "TARGET_CHANGES":
            _FakeRepository.previous_candidate = (
                "C_OTHER_PREVIOUS"
            )

        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        if exc_type is not None:
            _FakeRepository.restore(
                self.before
            )

        return False


class _FakeEngine:
    def connect(
        self,
    ):
        return _ConnectContext()

    def begin(
        self,
    ):
        return _Transaction()


def _patch(
    monkeypatch,
):
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


def _execute():
    return (
        promotion_service
        .execute_emergency_rollback(
            horizon=1,
            confirmation=(
                promotion_service
                .ROLLBACK_CONFIRMATION_PHRASE
            ),
            requested_by="acceptance",
            reason=(
                "Emergency rollback "
                "acceptance verification"
            ),
        )
    )


def test_rollback_without_daily_lock_is_immediate_and_preserves_official(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=False
    )

    _patch(
        monkeypatch
    )

    lock_before = deepcopy(
        _FakeRepository
        .daily_lock_state
    )

    official_before = deepcopy(
        _FakeRepository
        .official_state
    )

    result = _execute()

    assert (
        result["status"]
        == "COMPLETED"
    )

    assert (
        result["change_kind"]
        == "EMERGENCY_ROLLBACK"
    )

    assert (
        result["items"][0]["effect"]
        == "IMMEDIATE"
    )

    assert (
        _FakeRepository.active_candidate
        == PREVIOUS
    )

    assert (
        _FakeRepository.scheduled_candidate
        is None
    )

    assert (
        _FakeRepository.daily_lock_state
        == lock_before
    )

    assert (
        _FakeRepository.official_state
        == official_before
    )


def test_rollback_with_daily_lock_is_next_cycle_and_preserves_current_day_state(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=True
    )

    _patch(
        monkeypatch
    )

    lock_before = deepcopy(
        _FakeRepository
        .daily_lock_state
    )

    official_before = deepcopy(
        _FakeRepository
        .official_state
    )

    result = _execute()

    assert (
        result["status"]
        == "COMPLETED"
    )

    assert (
        result["items"][0]["effect"]
        == "NEXT_CYCLE"
    )

    assert (
        result["items"][0][
            "effective_from_business_date"
        ]
        == "2026-07-01"
    )

    # Current-day Production không đổi.
    assert (
        _FakeRepository.active_candidate
        == CURRENT
    )

    assert (
        _FakeRepository.scheduled_candidate
        == PREVIOUS
    )

    assert (
        _FakeRepository.scheduled_effective_from
        == date(
            2026,
            7,
            1,
        )
    )

    assert (
        _FakeRepository.daily_lock_state
        == lock_before
    )

    assert (
        _FakeRepository.official_state
        == official_before
    )


def test_rollback_rejects_lock_state_change_between_preview_and_commit(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=False
    )

    _FakeRepository.mutate_on_begin = (
        "LOCK_APPEARS"
    )

    _patch(
        monkeypatch
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
        _execute()

    # Transaction exception phải rollback
    # mọi mutation/write trong fake state.
    after = (
        _FakeRepository.snapshot()
    )

    assert after == before


def test_rollback_rejects_active_candidate_change_between_preview_and_commit(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=False
    )

    _FakeRepository.mutate_on_begin = (
        "ACTIVE_CHANGES"
    )

    _patch(
        monkeypatch
    )

    before = (
        _FakeRepository.snapshot()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "ACTIVE Production changed"
        ),
    ):
        _execute()

    assert (
        _FakeRepository.snapshot()
        == before
    )


def test_rollback_rejects_target_change_between_preview_and_commit(
    monkeypatch,
):
    _FakeRepository.reset(
        lock_present=False
    )

    _FakeRepository.mutate_on_begin = (
        "TARGET_CHANGES"
    )

    _patch(
        monkeypatch
    )

    before = (
        _FakeRepository.snapshot()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Rollback target changed"
        ),
    ):
        _execute()

    assert (
        _FakeRepository.snapshot()
        == before
    )
