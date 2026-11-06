from copy import deepcopy
from datetime import date

import src.monitoring.service as monitoring_service


ORIGIN_DATE = date(2026, 6, 30)
TARGET_DATE = date(2026, 7, 1)

OFFICIAL_ID = "OFF_MATCH_ACCEPTANCE"
CANDIDATE_ID = "TRN_TEST_H1_RF"


class _Context:
    def __enter__(self):
        return object()

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False


class _Engine:
    def begin(self):
        return _Context()


class _FakeRepository:
    contexts = []
    matches = {}
    writes = []

    @classmethod
    def reset(cls):
        cls.contexts = []
        cls.matches = {}
        cls.writes = []

    def __init__(
        self,
        conn,
    ):
        self.conn = conn

    def official_actual_context_rows(
        self,
    ):
        return deepcopy(
            self.__class__.contexts
        )

    def latest_actual_date(
        self,
    ):
        dates = [
            row[
                "department_latest_actual_date"
            ]
            for row in self.__class__.contexts
            if row[
                "department_latest_actual_date"
            ]
            is not None
        ]

        if not dates:
            return None

        return max(dates)

    def existing_match(
        self,
        official_id,
    ):
        row = (
            self.__class__
            .matches
            .get(official_id)
        )

        return (
            None
            if row is None
            else deepcopy(row)
        )

    def insert_match(
        self,
        row,
    ):
        official_id = row["official_id"]

        assert (
            official_id
            not in self.__class__.matches
        )

        saved = deepcopy(row)

        saved["match_revision_no"] = 1

        self.__class__.matches[
            official_id
        ] = saved

        self.__class__.writes.append(
            (
                "INSERT",
                official_id,
            )
        )

    def update_match(
        self,
        row,
    ):
        official_id = row["official_id"]

        assert (
            official_id
            in self.__class__.matches
        )

        previous = (
            self.__class__.matches[
                official_id
            ]
        )

        saved = deepcopy(row)

        saved["match_revision_no"] = (
            int(
                previous[
                    "match_revision_no"
                ]
            )
            + 1
        )

        self.__class__.matches[
            official_id
        ] = saved

        self.__class__.writes.append(
            (
                "UPDATE",
                official_id,
            )
        )

    def match_count(
        self,
    ):
        return len(
            self.__class__.matches
        )


def _official_context(
    *,
    actual_occupied_beds,
    actual_source_revision_no,
    department_latest_actual_date,
):
    return {
        "official_id": OFFICIAL_ID,
        "origin_date": ORIGIN_DATE,
        "target_date": TARGET_DATE,
        "department_id": 343,
        "horizon": 1,
        "candidate_id": CANDIDATE_ID,
        "planned_beds": 55,
        "prediction_raw": 46.9,
        "prediction_rounded": 47,
        "capacity_alert": False,
        "actual_occupied_beds": (
            actual_occupied_beds
        ),
        "actual_quality_flag": (
            None
            if actual_occupied_beds
            is None
            else "CLEAN"
        ),
        "actual_source_revision_no": (
            actual_source_revision_no
        ),
        "department_latest_actual_date": (
            department_latest_actual_date
        ),
    }


def _patch(
    monkeypatch,
):
    monkeypatch.setattr(
        monitoring_service,
        "create_sql_engine",
        lambda: _Engine(),
    )

    monkeypatch.setattr(
        monitoring_service,
        "MonitoringRepository",
        _FakeRepository,
    )


def test_future_actual_remains_waiting_without_match(
    monkeypatch,
):
    _FakeRepository.reset()

    _FakeRepository.contexts = [
        _official_context(
            actual_occupied_beds=None,
            actual_source_revision_no=None,
            department_latest_actual_date=(
                ORIGIN_DATE
            ),
        )
    ]

    _patch(
        monkeypatch
    )

    result = (
        monitoring_service
        .run_actual_matching()
    )

    assert (
        result["status"]
        == "WAITING_FOR_ACTUAL"
    )

    assert (
        result["official_total_count"]
        == 1
    )

    assert (
        result["matched_total_count"]
        == 0
    )

    assert (
        result["waiting_for_actual_count"]
        == 1
    )

    assert (
        result["missing_actual_count"]
        == 0
    )

    assert (
        _FakeRepository.matches
        == {}
    )

    assert (
        _FakeRepository.writes
        == []
    )


def test_actual_matching_rerun_same_evidence_is_idempotent(
    monkeypatch,
):
    _FakeRepository.reset()

    _FakeRepository.contexts = [
        _official_context(
            actual_occupied_beds=49,
            actual_source_revision_no=1,
            department_latest_actual_date=(
                TARGET_DATE
            ),
        )
    ]

    _patch(
        monkeypatch
    )

    first = (
        monitoring_service
        .run_actual_matching()
    )

    assert (
        first["status"]
        == "COMPLETED"
    )

    assert (
        first["inserted_match_count"]
        == 1
    )

    assert (
        first["updated_match_count"]
        == 0
    )

    assert (
        first["unchanged_match_count"]
        == 0
    )

    assert len(
        _FakeRepository.matches
    ) == 1

    first_match = deepcopy(
        _FakeRepository.matches[
            OFFICIAL_ID
        ]
    )

    second = (
        monitoring_service
        .run_actual_matching()
    )

    assert (
        second["status"]
        == "COMPLETED"
    )

    assert (
        second["inserted_match_count"]
        == 0
    )

    assert (
        second["updated_match_count"]
        == 0
    )

    assert (
        second["unchanged_match_count"]
        == 1
    )

    assert len(
        _FakeRepository.matches
    ) == 1

    assert (
        _FakeRepository.matches[
            OFFICIAL_ID
        ]
        == first_match
    )

    assert (
        _FakeRepository.writes
        == [
            (
                "INSERT",
                OFFICIAL_ID,
            )
        ]
    )


def test_source_correction_updates_same_official_match_revision(
    monkeypatch,
):
    _FakeRepository.reset()

    _FakeRepository.contexts = [
        _official_context(
            actual_occupied_beds=49,
            actual_source_revision_no=1,
            department_latest_actual_date=(
                TARGET_DATE
            ),
        )
    ]

    _patch(
        monkeypatch
    )

    first = (
        monitoring_service
        .run_actual_matching()
    )

    assert (
        first["inserted_match_count"]
        == 1
    )

    assert (
        _FakeRepository.matches[
            OFFICIAL_ID
        ][
            "match_revision_no"
        ]
        == 1
    )

    # Source correction:
    # cùng Official, Actual mới và source revision mới.
    _FakeRepository.contexts = [
        _official_context(
            actual_occupied_beds=50,
            actual_source_revision_no=2,
            department_latest_actual_date=(
                TARGET_DATE
            ),
        )
    ]

    second = (
        monitoring_service
        .run_actual_matching()
    )

    assert (
        second["status"]
        == "COMPLETED"
    )

    assert (
        second["inserted_match_count"]
        == 0
    )

    assert (
        second["updated_match_count"]
        == 1
    )

    assert (
        second["unchanged_match_count"]
        == 0
    )

    # Vẫn chỉ một row theo official_id.
    assert len(
        _FakeRepository.matches
    ) == 1

    corrected = (
        _FakeRepository.matches[
            OFFICIAL_ID
        ]
    )

    assert (
        corrected[
            "actual_occupied_beds"
        ]
        == 50
    )

    assert (
        corrected[
            "actual_source_revision_no"
        ]
        == 2
    )

    assert (
        corrected[
            "match_revision_no"
        ]
        == 2
    )

    assert (
        _FakeRepository.writes
        == [
            (
                "INSERT",
                OFFICIAL_ID,
            ),
            (
                "UPDATE",
                OFFICIAL_ID,
            ),
        ]
    )
