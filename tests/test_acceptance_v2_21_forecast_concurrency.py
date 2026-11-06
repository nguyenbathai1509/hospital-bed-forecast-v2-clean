from copy import deepcopy
from datetime import date

import src.forecast.service as forecast_service


ORIGIN = date(2026, 6, 30)
TARGET = date(2026, 7, 1)

DRAFT_ID = "DRF_CONCURRENCY_TEST"
OFFICIAL_ID = "OFF_CONCURRENCY_WINNER"
CANDIDATE_ID = "TRN_TEST_H1_RF"


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
    official = None
    writes = []
    force_stale_plan = False

    @classmethod
    def reset(cls):
        cls.draft = {
            "draft_id": DRAFT_ID,
            "origin_date": ORIGIN,
            "department_id": 343,
            "horizon": 1,
            "target_date": TARGET,
            "candidate_id": CANDIDATE_ID,
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

        cls.official = None
        cls.writes = []
        cls.force_stale_plan = False

    def __init__(self, conn):
        self.conn = conn

    def list_open_drafts(
        self,
        *,
        origin_date,
    ):
        assert origin_date == ORIGIN

        # Bình thường chỉ trả Draft mở.
        if (
            self.__class__.draft["status"]
            == "DRAFT"
        ):
            return [
                deepcopy(
                    self.__class__.draft
                )
            ]

        # Mô phỏng request B đã lập plan
        # trước khi request A commit.
        if self.__class__.force_stale_plan:
            stale = deepcopy(
                self.__class__.draft
            )
            stale["status"] = "DRAFT"
            return [stale]

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

        if self.__class__.official is None:
            return None

        return deepcopy(
            self.__class__.official
        )

    def official_for_key(
        self,
        *,
        origin_date,
        department_id,
        horizon,
    ):
        if self.__class__.official is None:
            return None

        row = self.__class__.official

        if (
            row["origin_date"] == origin_date
            and row["department_id"]
            == department_id
            and row["horizon"] == horizon
        ):
            return deepcopy(row)

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

        return CANDIDATE_ID

    def insert_daily_lock(
        self,
        **kwargs,
    ):
        raise AssertionError(
            "Lock already exists in this test."
        )

    def insert_official(
        self,
        *,
        official_id,
        draft,
        confirmed_by,
    ):
        assert (
            self.__class__.official
            is None
        ), "Duplicate Official insert attempted"

        self.__class__.official = {
            "official_id": official_id,
            "source_draft_id": (
                draft["draft_id"]
            ),
            "origin_date": (
                draft["origin_date"]
            ),
            "department_id": (
                draft["department_id"]
            ),
            "horizon": (
                draft["horizon"]
            ),
            "candidate_id": (
                draft["candidate_id"]
            ),
            "confirmed_by": confirmed_by,
        }

        self.__class__.writes.append(
            (
                "insert_official",
                official_id,
            )
        )

    def mark_draft_confirmed(
        self,
        draft_id,
    ):
        assert draft_id == DRAFT_ID

        self.__class__.draft["status"] = (
            "CONFIRMED"
        )

        self.__class__.writes.append(
            (
                "mark_draft_confirmed",
                draft_id,
            )
        )


def test_concurrent_confirmation_stale_plan_does_not_duplicate_official(
    monkeypatch,
):
    _FakeRepository.reset()

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

    monkeypatch.setattr(
        forecast_service,
        "_new_id",
        lambda prefix: OFFICIAL_ID,
    )

    # ---------------------------------
    # Request A thắng race.
    # ---------------------------------
    first = (
        forecast_service.confirm_officials(
            confirmation=(
                forecast_service
                .OFFICIAL_CONFIRMATION_PHRASE
            ),
            origin_date=ORIGIN,
            confirmed_by="request-a",
        )
    )

    assert first["status"] == "COMPLETED"
    assert first["official_count"] == 1

    assert (
        _FakeRepository.draft["status"]
        == "CONFIRMED"
    )

    assert (
        _FakeRepository.official[
            "official_id"
        ]
        == OFFICIAL_ID
    )

    state_after_a = {
        "draft": deepcopy(
            _FakeRepository.draft
        ),
        "official": deepcopy(
            _FakeRepository.official
        ),
        "writes": deepcopy(
            _FakeRepository.writes
        ),
    }

    # ---------------------------------
    # Request B:
    # mô phỏng stale plan đã lấy trước A.
    # ---------------------------------
    _FakeRepository.force_stale_plan = True

    second = (
        forecast_service.confirm_officials(
            confirmation=(
                forecast_service
                .OFFICIAL_CONFIRMATION_PHRASE
            ),
            origin_date=ORIGIN,
            confirmed_by="request-b",
        )
    )

    assert second["status"] == "COMPLETED"
    assert second["official_count"] == 0
    assert len(second["results"]) == 1

    row = second["results"][0]

    assert (
        row["status"]
        == "ALREADY_OFFICIAL"
    )

    assert row["draft_id"] == DRAFT_ID

    assert (
        row["official_id"]
        == OFFICIAL_ID
    )

    # ---------------------------------
    # Không duplicate / overwrite.
    # ---------------------------------
    assert (
        _FakeRepository.draft
        == state_after_a["draft"]
    )

    assert (
        _FakeRepository.official
        == state_after_a["official"]
    )

    assert (
        _FakeRepository.writes
        == state_after_a["writes"]
    )

    assert (
        _FakeRepository.official[
            "confirmed_by"
        ]
        == "request-a"
    )

    assert [
        item[0]
        for item in _FakeRepository.writes
    ] == [
        "insert_official",
        "mark_draft_confirmed",
    ]
