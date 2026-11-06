from datetime import date

from src.promotion.repository import (
    ProductionRepository,
)


BUSINESS_DATE = date(2026, 7, 1)

OLD_CANDIDATE = "TRN_OLD_H1_RF"
NEW_CANDIDATE = "TRN_NEW_H1_SVR"

ACTIVE_ID = 10
SCHEDULED_ID = 20


class _Result:
    def __init__(
        self,
        *,
        rows=None,
        first=None,
        scalar=None,
    ):
        self._rows = (
            []
            if rows is None
            else rows
        )

        self._first = first
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar


class _FakeConnection:
    def __init__(
        self,
        *,
        lock_present,
    ):
        self.lock_present = (
            lock_present
        )

        self.operations = []

    def execute(
        self,
        statement,
        params=None,
    ):
        sql = " ".join(
            str(statement).split()
        )

        params = (
            {}
            if params is None
            else params
        )

        # ---------------------------------
        # Due scheduled candidates.
        # ---------------------------------
        if (
            "FROM dbo.production_models"
            in sql
            and "slot_status='SCHEDULED'"
            in sql
            and "effective_from_business_date<=:business_date"
            in sql
        ):
            assert (
                params["business_date"]
                == BUSINESS_DATE
            )

            return _Result(
                rows=[
                    {
                        "production_id": (
                            SCHEDULED_ID
                        ),
                        "horizon": 1,
                        "candidate_id": (
                            NEW_CANDIDATE
                        ),
                        "effective_from_business_date": (
                            BUSINESS_DATE
                        ),
                        "promoted_by": (
                            "acceptance"
                        ),
                        "promotion_reason": (
                            "NEXT_CYCLE test"
                        ),
                    }
                ]
            )

        # ---------------------------------
        # Daily Model Lock guard.
        # ---------------------------------
        if (
            "FROM dbo.daily_model_locks"
            in sql
        ):
            assert (
                params["business_date"]
                == BUSINESS_DATE
            )

            assert (
                params["horizon"]
                == 1
            )

            return _Result(
                scalar=(
                    1
                    if self.lock_present
                    else None
                )
            )

        # ---------------------------------
        # Existing ACTIVE Production.
        # ---------------------------------
        if (
            "FROM dbo.production_models"
            in sql
            and "slot_status='ACTIVE'"
            in sql
        ):
            assert params["horizon"] == 1

            return _Result(
                first={
                    "production_id": (
                        ACTIVE_ID
                    ),
                    "candidate_id": (
                        OLD_CANDIDATE
                    ),
                }
            )

        # ---------------------------------
        # Retire current ACTIVE.
        # ---------------------------------
        if (
            "UPDATE dbo.production_models"
            in sql
            and "slot_status='RETIRED'"
            in sql
        ):
            assert (
                params["production_id"]
                == ACTIVE_ID
            )

            assert (
                params["effective_to"]
                == BUSINESS_DATE
            )

            self.operations.append(
                "RETIRE_ACTIVE"
            )

            return _Result()

        # ---------------------------------
        # Archive old candidate.
        # ---------------------------------
        if (
            "UPDATE dbo.model_candidates"
            in sql
            and "registry_status='ARCHIVED'"
            in sql
        ):
            assert (
                params["candidate_id"]
                == OLD_CANDIDATE
            )

            self.operations.append(
                "ARCHIVE_OLD"
            )

            return _Result()

        # ---------------------------------
        # Scheduled -> ACTIVE.
        # ---------------------------------
        if (
            "UPDATE dbo.production_models"
            in sql
            and "SET slot_status='ACTIVE'"
            in sql
        ):
            assert (
                params["production_id"]
                == SCHEDULED_ID
            )

            self.operations.append(
                "ACTIVATE_SCHEDULED"
            )

            return _Result()

        # ---------------------------------
        # Candidate -> PRODUCTION.
        # ---------------------------------
        if (
            "UPDATE dbo.model_candidates"
            in sql
            and "registry_status='PRODUCTION'"
            in sql
        ):
            assert (
                params["candidate_id"]
                == NEW_CANDIDATE
            )

            self.operations.append(
                "MARK_NEW_PRODUCTION"
            )

            return _Result()

        # ---------------------------------
        # Mark NEXT_CYCLE item applied.
        # ---------------------------------
        if (
            "UPDATE pci"
            in sql
            and "pci.effect='NEXT_CYCLE'"
            in sql
        ):
            assert params["horizon"] == 1

            assert (
                params["candidate_id"]
                == NEW_CANDIDATE
            )

            self.operations.append(
                "MARK_CHANGE_APPLIED"
            )

            return _Result()

        raise AssertionError(
            f"Unexpected SQL:\n{sql}\n"
            f"params={params}"
        )


def test_due_next_cycle_is_blocked_when_new_cycle_already_locked():
    conn = _FakeConnection(
        lock_present=True
    )

    repo = ProductionRepository(
        conn
    )

    activated = (
        repo.activate_due_scheduled(
            BUSINESS_DATE
        )
    )

    assert activated == []

    # Không được retire ACTIVE hay activate candidate mới.
    assert conn.operations == []


def test_due_next_cycle_activates_when_cycle_is_not_locked():
    conn = _FakeConnection(
        lock_present=False
    )

    repo = ProductionRepository(
        conn
    )

    activated = (
        repo.activate_due_scheduled(
            BUSINESS_DATE
        )
    )

    assert activated == [
        {
            "horizon": 1,
            "candidate_id": (
                NEW_CANDIDATE
            ),
            "effective_from_business_date": (
                str(BUSINESS_DATE)
            ),
        }
    ]

    assert conn.operations == [
        "RETIRE_ACTIVE",
        "ARCHIVE_OLD",
        "ACTIVATE_SCHEDULED",
        "MARK_NEW_PRODUCTION",
        "MARK_CHANGE_APPLIED",
    ]
