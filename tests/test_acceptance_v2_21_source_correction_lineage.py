from copy import deepcopy
from datetime import date, timedelta

from src.db.repositories.core import (
    CoreRepository,
)
from src.features.builder import (
    build_features,
)
from src.ml.sample_builder import (
    build_ml_samples,
)


DEPARTMENT_ID = 343


class _Result:
    def __init__(
        self,
        *,
        mapping=None,
        scalar=None,
    ):
        self.mapping = mapping
        self.scalar = scalar

    def mappings(
        self,
    ):
        return self

    def first(
        self,
    ):
        return self.mapping

    def scalar_one(
        self,
    ):
        return self.scalar


class _RawConnection:
    def __init__(
        self,
    ):
        self.source_hash = "A" * 64
        self.revision_no = 1
        self.update_sql = None

    def execute(
        self,
        stmt,
        params=None,
    ):
        sql = " ".join(
            str(stmt).split()
        )

        if (
            "SELECT source_hash, revision_no "
            "FROM dbo.raw_bed_daily"
            in sql
        ):
            return _Result(
                mapping={
                    "source_hash":
                        self.source_hash,
                    "revision_no":
                        self.revision_no,
                }
            )

        if (
            "UPDATE dbo.raw_bed_daily SET"
            in sql
        ):
            self.update_sql = str(
                stmt
            )

            self.source_hash = (
                params["source_hash"]
            )

            self.revision_no += 1

            return _Result()

        if (
            "INSERT INTO dbo.raw_bed_daily"
            in sql
        ):
            raise AssertionError(
                "Existing business key "
                "must be updated, not inserted"
            )

        raise AssertionError(
            f"Unexpected SQL: {sql}"
        )


class _CleanConnection:
    def __init__(
        self,
        raw_revision,
    ):
        self.raw_revision = (
            raw_revision
        )

        self.clean_payload = None

    def execute(
        self,
        stmt,
        params=None,
    ):
        sql = " ".join(
            str(stmt).split()
        )

        if (
            "SELECT revision_no "
            "FROM dbo.raw_bed_daily"
            in sql
        ):
            return _Result(
                scalar=self.raw_revision
            )

        if (
            "UPDATE dbo.clean_bed_daily"
            in sql
        ):
            self.clean_payload = dict(
                params
            )

            return _Result()

        raise AssertionError(
            f"Unexpected SQL: {sql}"
        )


def _raw_row(
    source_hash,
):
    return {
        "business_date":
            date(2026, 1, 5),
        "source_weekday":
            "Monday",
        "source_month":
            1,
        "department_id":
            DEPARTMENT_ID,
        "department_code":
            "ICU343",
        "department_name":
            "ICU",
        "planned_beds":
            60,
        "occupied_start":
            50,
        "admissions":
            5,
        "transfer_in":
            1,
        "discharges":
            3,
        "transfer_out":
            1,
        "occupied_end":
            52,
        "occupied_beds":
            52,
        "balance_status":
            "PASS",
        "occupancy_rate":
            52 / 60,
        "source_file":
            "acceptance.xlsx",
        "source_row_num":
            5,
        "source_hash":
            source_hash,
    }


def _clean_history():
    start = date(
        2026,
        1,
        1,
    )

    rows = []

    for index in range(8):
        rows.append(
            {
                "business_date":
                    start
                    + timedelta(
                        days=index
                    ),
                "department_id":
                    DEPARTMENT_ID,
                "planned_beds":
                    60,
                "occupied_beds":
                    40 + index,
                "admissions":
                    5,
                "discharges":
                    3,
                "transfer_in":
                    1,
                "transfer_out":
                    1,
                "source_revision_no":
                    1,
            }
        )

    return rows


def _feature_by_date(
    rows,
):
    return {
        row["origin_date"]:
            row
        for row in rows
    }


def _sample_by_key(
    rows,
):
    return {
        (
            row["origin_date"],
            row["department_id"],
            row["horizon"],
        ):
            row
        for row in rows
    }


def test_raw_correction_increments_revision_and_clean_copies_it():
    raw_conn = (
        _RawConnection()
    )

    raw_repo = (
        CoreRepository(
            raw_conn
        )
    )

    corrected = _raw_row(
        "B" * 64
    )

    first = (
        raw_repo.upsert_raw(
            [corrected],
            "DAY_CORRECTION",
        )
    )

    assert first == {
        "inserted": 0,
        "updated": 1,
        "unchanged": 0,
    }

    assert (
        raw_conn.revision_no
        == 2
    )

    assert (
        "revision_no=revision_no + 1"
        in raw_conn.update_sql
    )

    # Rerun cùng corrected evidence:
    # phải idempotent, không tăng revision tiếp.
    second = (
        raw_repo.upsert_raw(
            [corrected],
            "DAY_CORRECTION_RERUN",
        )
    )

    assert second == {
        "inserted": 0,
        "updated": 0,
        "unchanged": 1,
    }

    assert (
        raw_conn.revision_no
        == 2
    )

    clean_conn = (
        _CleanConnection(
            raw_conn.revision_no
        )
    )

    clean_repo = (
        CoreRepository(
            clean_conn
        )
    )

    clean_repo.upsert_clean(
        [corrected],
        "DAY_CORRECTION",
        {},
    )

    assert (
        clean_conn.clean_payload[
            "source_revision_no"
        ]
        == 2
    )


def test_source_correction_rebuilds_features_and_ml_samples():
    initial_clean = (
        _clean_history()
    )

    initial_features = (
        build_features(
            initial_clean,
            "v2.0",
        )
    )

    initial_samples = (
        build_ml_samples(
            feature_rows=(
                initial_features
            ),
            clean_rows=(
                initial_clean
            ),
            feature_version="v2.0",
            data_version="DV_BEFORE",
        )
    )

    corrected_clean = deepcopy(
        initial_clean
    )

    # 2026-01-05:
    # Actual correction 44 -> 54,
    # source revision 1 -> 2.
    corrected_clean[4][
        "occupied_beds"
    ] = 54

    corrected_clean[4][
        "source_revision_no"
    ] = 2

    corrected_features = (
        build_features(
            corrected_clean,
            "v2.0",
        )
    )

    corrected_samples = (
        build_ml_samples(
            feature_rows=(
                corrected_features
            ),
            clean_rows=(
                corrected_clean
            ),
            feature_version="v2.0",
            data_version="DV_AFTER",
        )
    )

    before_feature = (
        _feature_by_date(
            initial_features
        )
    )

    after_feature = (
        _feature_by_date(
            corrected_features
        )
    )

    corrected_date = date(
        2026,
        1,
        5,
    )

    assert (
        before_feature[
            corrected_date
        ][
            "source_revision_no"
        ]
        == 1
    )

    assert (
        after_feature[
            corrected_date
        ][
            "source_revision_no"
        ]
        == 2
    )

    # Correction phải lan xuống lag.
    assert (
        before_feature[
            date(
                2026,
                1,
                6,
            )
        ][
            "occupied_beds_lag_1"
        ]
        == 44
    )

    assert (
        after_feature[
            date(
                2026,
                1,
                6,
            )
        ][
            "occupied_beds_lag_1"
        ]
        == 54
    )

    assert (
        before_feature[
            date(
                2026,
                1,
                8,
            )
        ][
            "occupied_beds_lag_3"
        ]
        == 44
    )

    assert (
        after_feature[
            date(
                2026,
                1,
                8,
            )
        ][
            "occupied_beds_lag_3"
        ]
        == 54
    )

    before_samples = (
        _sample_by_key(
            initial_samples
        )
    )

    after_samples = (
        _sample_by_key(
            corrected_samples
        )
    )

    # H+1 sample origin 04/01
    # lấy Actual đúng ngày 05/01.
    sample_key = (
        date(
            2026,
            1,
            4,
        ),
        DEPARTMENT_ID,
        1,
    )

    assert (
        before_samples[
            sample_key
        ][
            "target_occupied_beds"
        ]
        == 44
    )

    assert (
        after_samples[
            sample_key
        ][
            "target_occupied_beds"
        ]
        == 54
    )

    assert all(
        row["data_version"]
        == "DV_AFTER"
        for row
        in corrected_samples
    )

    # Full rebuild không được sinh
    # duplicate business keys.
    unique_keys = [
        (
            row["origin_date"],
            row["department_id"],
            row["horizon"],
            row["feature_version"],
        )
        for row
        in corrected_samples
    ]

    assert (
        len(unique_keys)
        == len(set(unique_keys))
    )

    # Correction refresh dữ liệu,
    # không tự nhân số sample.
    assert (
        len(corrected_samples)
        == len(initial_samples)
    )
