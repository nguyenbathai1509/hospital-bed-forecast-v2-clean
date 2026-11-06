from copy import deepcopy
from datetime import date

import pytest

import src.forecast.service as forecast_service


ORIGIN = date(2026, 6, 30)
TARGET = date(2026, 7, 1)

DRAFT_ID = "DRF_STALE_LOCK_TEST"

DRAFT_CANDIDATE = (
    "TRN_TEST_H1_RF"
)

LOCKED_CANDIDATE = (
    "TRN_OTHER_H1_SVR"
)


class _FakeContext:
    def __enter__(self):
        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class _FakeEngine:
    def connect(self):
        return _FakeContext()

    def begin(self):
        return _FakeContext()


class _FakeRepository:
    draft = {}
    writes = []

    @classmethod
    def reset(cls):
        cls.draft = {
            "draft_id": DRAFT_ID,
            "origin_date": ORIGIN,
            "department_id": 343,
            "horizon": 1,
            "target_date": TARGET,
            "candidate_id": DRAFT_CANDIDATE,
            "source_mode": "PRODUCTION",
            "status": "DRAFT",
            "prediction_raw": 46.9,
            "prediction_rounded": 47,
            "planned_beds": 55,
            "predicted_utilization_pct": 85.27,
            "capacity_alert": False,
            "capacity_excess_beds": 0,
            "feature_version": "v2.0",
            "data_version": "excel-sha256:test",
            "created_by": "acceptance-test",
        }

        cls.writes = []

    def __init__(self, conn):
        self.conn = conn

    def list_open_drafts(
        self,
        *,
        origin_date,
    ):
        if (
            origin_date == ORIGIN
            and self.__class__.draft["status"]
            == "DRAFT"
        ):
            return [
                deepcopy(
                    self.__class__.draft
                )
            ]

        return []

    def draft_for_update(
        self,
        draft_id,
    ):
        assert draft_id == DRAFT_ID

        return deepcopy(
            self.__class__.draft
        )

    def official_by_source_draft(
        self,
        draft_id,
    ):
        assert draft_id == DRAFT_ID
        return None

    def official_for_key(
        self,
        *,
        origin_date,
        department_id,
        horizon,
    ):
        assert origin_date == ORIGIN
        assert department_id == 343
        assert horizon == 1

        return None

    def daily_lock_candidate_id(
        self,
        *,
        origin_date,
        horizon,
        for_update=False,
    ):
        assert origin_date == ORIGIN
        assert horizon == 1
        assert for_update is True

        # Lock đã tồn tại nhưng dùng model khác.
        return LOCKED_CANDIDATE

    def insert_daily_lock(
        self,
        **kwargs,
    ):
        self.__class__.writes.append(
            "insert_daily_lock"
        )

        raise AssertionError(
            "Must not insert a new lock "
            "when stale lock already exists."
        )

    def insert_official(
        self,
        **kwargs,
    ):
        self.__class__.writes.append(
            "insert_official"
        )

        raise AssertionError(
            "Official must not be inserted "
            "when model lock mismatches."
        )

    def mark_draft_confirmed(
        self,
        draft_id,
    ):
        self.__class__.writes.append(
            "mark_draft_confirmed"
        )

        raise AssertionError(
            "Draft must remain DRAFT "
            "when model lock mismatches."
        )


def test_stale_daily_model_lock_blocks_official_confirmation(
    monkeypatch,
):
    _FakeRepository.reset()

    before = deepcopy(
        _FakeRepository.draft
    )

    monkeypatch.setattr(
        forecast_service,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )

    monkeypatch.setattr(
        forecast_service,
        "ForecastRepository",
        _FakeRepository,
    )

    monkeypatch.setattr(
        forecast_service,
        "_resolve_origin_date",
        lambda repo, origin_date: (
            origin_date or ORIGIN,
            "excel-sha256:test",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "STALE_DRAFT_MODEL_LOCK_MISMATCH"
        ),
    ):
        forecast_service.confirm_officials(
            confirmation=(
                forecast_service
                .OFFICIAL_CONFIRMATION_PHRASE
            ),
            origin_date=ORIGIN,
            confirmed_by="acceptance",
        )

    # Không được có bất kỳ write nào.
    assert (
        _FakeRepository.writes
        == []
    )

    # Draft vẫn nguyên trạng.
    assert (
        _FakeRepository.draft
        == before
    )

    assert (
        _FakeRepository.draft["status"]
        == "DRAFT"
    )
