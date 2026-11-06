from copy import deepcopy
from datetime import date

import src.forecast.service as forecast_service


ORIGIN = date(2026, 6, 30)
TARGET = date(2026, 7, 1)

DRAFT_ID = "DRF_ACCEPTANCE_TEST"
OFFICIAL_ID = "OFF_ACCEPTANCE_TEST"
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
    officials = {}
    locks = {}
    writes = []

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
            "prediction_raw": 46.9362457242168,
            "prediction_rounded": 47,
            "planned_beds": 55,
            "predicted_utilization_pct": 85.3386285894851,
            "capacity_alert": False,
            "capacity_excess_beds": 0,
            "feature_version": "v2.0",
            "data_version": "excel-sha256:test",
            "created_by": "acceptance-test",
        }

        cls.officials = {}
        cls.locks = {}
        cls.writes = []

    def __init__(self, conn):
        self.conn = conn

    def list_open_drafts(
        self,
        *,
        origin_date,
    ):
        if (
            self.__class__.draft["origin_date"]
            == origin_date
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
        if (
            draft_id
            != self.__class__.draft["draft_id"]
        ):
            return None

        return deepcopy(
            self.__class__.draft
        )

    def official_by_source_draft(
        self,
        draft_id,
    ):
        for row in (
            self.__class__.officials.values()
        ):
            if (
                row["source_draft_id"]
                == draft_id
            ):
                return deepcopy(row)

        return None

    def official_for_key(
        self,
        *,
        origin_date,
        department_id,
        horizon,
    ):
        for row in (
            self.__class__.officials.values()
        ):
            if (
                row["origin_date"]
                == origin_date
                and row["department_id"]
                == department_id
                and row["horizon"]
                == horizon
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
        return self.__class__.locks.get(
            (
                origin_date,
                horizon,
            )
        )

    def insert_daily_lock(
        self,
        *,
        origin_date,
        horizon,
        candidate_id,
        trigger_department_id,
    ):
        key = (
            origin_date,
            horizon,
        )

        assert (
            key
            not in self.__class__.locks
        )

        self.__class__.locks[key] = (
            candidate_id
        )

        self.__class__.writes.append(
            (
                "insert_daily_lock",
                key,
                candidate_id,
                trigger_department_id,
            )
        )

    def insert_official(
        self,
        *,
        official_id,
        draft,
        confirmed_by,
    ):
        assert (
            official_id
            not in self.__class__.officials
        )

        row = {
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
            "target_date": (
                draft["target_date"]
            ),
            "candidate_id": (
                draft["candidate_id"]
            ),
            "prediction_raw": (
                draft["prediction_raw"]
            ),
            "prediction_rounded": (
                draft["prediction_rounded"]
            ),
            "planned_beds": (
                draft["planned_beds"]
            ),
            "predicted_utilization_pct": (
                draft[
                    "predicted_utilization_pct"
                ]
            ),
            "capacity_alert": (
                draft["capacity_alert"]
            ),
            "capacity_excess_beds": (
                draft[
                    "capacity_excess_beds"
                ]
            ),
            "feature_version": (
                draft["feature_version"]
            ),
            "data_version": (
                draft["data_version"]
            ),
            "confirmed_by": confirmed_by,
        }

        self.__class__.officials[
            official_id
        ] = row

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
        assert (
            draft_id
            == self.__class__.draft["draft_id"]
        )

        assert (
            self.__class__.draft["status"]
            == "DRAFT"
        )

        self.__class__.draft["status"] = (
            "CONFIRMED"
        )

        self.__class__.writes.append(
            (
                "mark_draft_confirmed",
                draft_id,
            )
        )


def test_draft_to_official_confirmation_is_safe_and_idempotent(
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

    # -----------------------------------------
    # Phase A:
    # Không có confirmation phrase.
    # Phải tuyệt đối read-only.
    # -----------------------------------------
    state_before = {
        "draft": deepcopy(
            _FakeRepository.draft
        ),
        "officials": deepcopy(
            _FakeRepository.officials
        ),
        "locks": deepcopy(
            _FakeRepository.locks
        ),
        "writes": list(
            _FakeRepository.writes
        ),
    }

    plan = (
        forecast_service.confirm_officials(
            confirmation=None,
            origin_date=ORIGIN,
            confirmed_by="acceptance",
        )
    )

    assert (
        plan["status"]
        == "CONFIRMATION_REQUIRED"
    )

    assert plan["draft_count"] == 1

    assert (
        _FakeRepository.draft
        == state_before["draft"]
    )

    assert (
        _FakeRepository.officials
        == state_before["officials"]
    )

    assert (
        _FakeRepository.locks
        == state_before["locks"]
    )

    assert (
        _FakeRepository.writes
        == state_before["writes"]
    )

    # -----------------------------------------
    # Phase B:
    # Phrase hợp lệ -> đúng 1 Official.
    # -----------------------------------------
    result = (
        forecast_service.confirm_officials(
            confirmation=(
                forecast_service
                .OFFICIAL_CONFIRMATION_PHRASE
            ),
            origin_date=ORIGIN,
            confirmed_by="acceptance",
        )
    )

    assert result["status"] == "COMPLETED"
    assert result["official_count"] == 1
    assert len(result["results"]) == 1

    row = result["results"][0]

    assert row["status"] == "OFFICIAL"
    assert row["official_id"] == OFFICIAL_ID
    assert row["draft_id"] == DRAFT_ID

    assert (
        _FakeRepository.draft["status"]
        == "CONFIRMED"
    )

    assert (
        _FakeRepository.locks[
            (ORIGIN, 1)
        ]
        == CANDIDATE_ID
    )

    assert len(
        _FakeRepository.officials
    ) == 1

    official = deepcopy(
        _FakeRepository.officials[
            OFFICIAL_ID
        ]
    )

    assert (
        official["source_draft_id"]
        == DRAFT_ID
    )

    assert (
        official["candidate_id"]
        == CANDIDATE_ID
    )

    assert (
        official["prediction_raw"]
        == 46.9362457242168
    )

    assert (
        official["prediction_rounded"]
        == 47
    )

    assert (
        official["confirmed_by"]
        == "acceptance"
    )

    assert [
        item[0]
        for item in _FakeRepository.writes
    ] == [
        "insert_daily_lock",
        "insert_official",
        "mark_draft_confirmed",
    ]

    state_after_first_confirm = {
        "draft": deepcopy(
            _FakeRepository.draft
        ),
        "officials": deepcopy(
            _FakeRepository.officials
        ),
        "locks": deepcopy(
            _FakeRepository.locks
        ),
        "writes": deepcopy(
            _FakeRepository.writes
        ),
    }

    # -----------------------------------------
    # Phase C:
    # Confirm lần hai.
    # Draft không còn mở -> NO_DRAFTS.
    # Không được duplicate/overwrite.
    # -----------------------------------------
    second = (
        forecast_service.confirm_officials(
            confirmation=(
                forecast_service
                .OFFICIAL_CONFIRMATION_PHRASE
            ),
            origin_date=ORIGIN,
            confirmed_by="someone-else",
        )
    )

    assert (
        second["status"]
        == "NO_DRAFTS"
    )

    assert second["draft_count"] == 0

    assert (
        _FakeRepository.draft
        == state_after_first_confirm[
            "draft"
        ]
    )

    assert (
        _FakeRepository.officials
        == state_after_first_confirm[
            "officials"
        ]
    )

    assert (
        _FakeRepository.locks
        == state_after_first_confirm[
            "locks"
        ]
    )

    assert (
        _FakeRepository.writes
        == state_after_first_confirm[
            "writes"
        ]
    )

    assert len(
        _FakeRepository.officials
    ) == 1

    assert (
        _FakeRepository.officials[
            OFFICIAL_ID
        ]["confirmed_by"]
        == "acceptance"
    )
