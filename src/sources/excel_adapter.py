from __future__ import annotations

from pathlib import Path

from src.bootstrap.excel_source import (
    load_excel_bootstrap,
)
from src.sources.base import (
    SourceBatch,
    SourceReadiness,
)


class ExcelSourceAdapter:
    """Development source adapter for the two verified hospital Excel exports.

    This is intentionally not described as a live HIS connection.

    It converts the Excel-specific bootstrap reader output into
    the source-neutral SourceBatch contract so a future read-only
    HospitalSqlSourceAdapter can replace it without changing
    RAW/CLEAN/FEATURE/ML pipeline code.
    """

    source_mode = "EXCEL_BOOTSTRAP"

    def __init__(
        self,
        paths: list[str | Path],
    ):
        self.paths = [
            Path(path)
            for path in paths
        ]

        self._cached_batch: (
            SourceBatch | None
        ) = None

    @property
    def source_ref(self) -> str:
        return ";".join(
            str(path)
            for path in self.paths
        )

    def _load(
        self,
    ) -> SourceBatch:
        if self._cached_batch is None:
            excel_batch = (
                load_excel_bootstrap(
                    self.paths
                )
            )

            self._cached_batch = SourceBatch(
                rows=excel_batch.rows,
                data_version=(
                    excel_batch.data_version
                ),
                source_refs=list(
                    excel_batch.source_files
                ),
            )

        return self._cached_batch

    def check_readiness(
        self,
    ) -> SourceReadiness:
        # Source file phải tồn tại trước.
        missing = [
            str(path)
            for path in self.paths
            if not path.exists()
        ]

        if missing:
            return SourceReadiness(
                ready=False,
                business_date=None,
                reason="SOURCE_FILES_MISSING",
                details={
                    "missing": missing
                },
            )

        # File tồn tại nhưng schema hoặc workbook lỗi
        # thì đây không còn là WAITING đơn thuần.
        try:
            batch = self._load()
        except Exception as exc:
            return SourceReadiness(
                ready=False,
                business_date=None,
                reason=(
                    "SOURCE_UNREADABLE_OR_SCHEMA_INVALID"
                ),
                details={
                    "error": str(exc)
                },
            )

        if not batch.rows:
            return SourceReadiness(
                ready=False,
                business_date=None,
                reason="SOURCE_EMPTY",
                details={},
            )

        max_by_department: dict[
            int, object
        ] = {}

        row_count_by_department: dict[
            int, int
        ] = {}

        for row in batch.rows:
            department_id = int(
                row["department_id"]
            )

            business_date = row[
                "business_date"
            ]

            row_count_by_department[
                department_id
            ] = (
                row_count_by_department.get(
                    department_id,
                    0,
                )
                + 1
            )

            if (
                department_id
                not in max_by_department
                or business_date
                > max_by_department[
                    department_id
                ]
            ):
                max_by_department[
                    department_id
                ] = business_date

        latest_dates = set(
            max_by_department.values()
        )

        # Mỗi khoa phải đóng dữ liệu đến cùng business date.
        if len(latest_dates) != 1:
            return SourceReadiness(
                ready=False,
                business_date=max(
                    latest_dates
                ),
                reason=(
                    "LATEST_DATE_NOT_ALIGNED_"
                    "ACROSS_DEPARTMENTS"
                ),
                details={
                    "max_date_by_department": {
                        str(k): str(v)
                        for k, v
                        in sorted(
                            max_by_department.items()
                        )
                    },
                    "row_count_by_department": {
                        str(k): v
                        for k, v
                        in sorted(
                            row_count_by_department.items()
                        )
                    },
                },
            )

        business_date = next(
            iter(latest_dates)
        )

        latest_departments = {
            int(row["department_id"])
            for row in batch.rows
            if row["business_date"]
            == business_date
        }

        all_departments = set(
            max_by_department
        )

        if (
            latest_departments
            != all_departments
        ):
            return SourceReadiness(
                ready=False,
                business_date=business_date,
                reason=(
                    "LATEST_DATE_MISSING_"
                    "ACTIVE_DEPARTMENT"
                ),
                details={
                    "all_departments": sorted(
                        all_departments
                    ),
                    "latest_departments": sorted(
                        latest_departments
                    ),
                },
            )

        return SourceReadiness(
            ready=True,
            business_date=business_date,
            reason="READY",
            details={
                "department_count": len(
                    all_departments
                ),
                "row_count": len(
                    batch.rows
                ),
                "source_refs": (
                    batch.source_refs
                ),
                "data_version": (
                    batch.data_version
                ),
            },
        )

    def extract(
        self,
    ) -> SourceBatch:
        readiness = (
            self.check_readiness()
        )

        if not readiness.ready:
            raise RuntimeError(
                "Source is not ready: "
                f"{readiness.reason}; "
                f"details={readiness.details}"
            )

        return self._load()