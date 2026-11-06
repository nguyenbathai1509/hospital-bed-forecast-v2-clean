from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.db.engine import create_sql_engine


DEMO_RESET_CONFIRMATION = "RESET DEMO STATE"


# Thứ tự DELETE đã được sắp theo quan hệ Foreign Key:
# bảng con trước -> bảng cha sau.
#
# Không xóa:
# - dbo.schema_migrations: lịch sử cấu trúc database.
# - dbo.departments: master/reference data của hệ thống.
RESET_DELETE_ORDER: tuple[str, ...] = (
    "official_actual_matches",
    "production_monitoring_metrics",
    "model_candidate_rankings",
    "model_evaluation_predictions",
    "model_metrics_by_department",
    "daily_model_locks",
    "official_forecasts",
    "forecast_drafts",
    "production_change_items",
    "production_models",
    "model_recommendations",
    "api_training_jobs",
    "production_monitoring_runs",
    "model_candidates",
    "training_runs",
    "production_changes",
    "bed_features_daily",
    "ml_samples",
    "clean_bed_daily",
    "raw_bed_daily",
    "data_quality_issues",
    "pipeline_runs",
)


# Không cho reset nếu một quy trình nền vẫn đang hoạt động.
BUSY_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "pipeline_runs",
        """
        SELECT COUNT(*)
        FROM dbo.pipeline_runs
        WHERE status = 'RUNNING'
        """,
    ),
    (
        "api_training_jobs",
        """
        SELECT COUNT(*)
        FROM dbo.api_training_jobs
        WHERE status IN ('PENDING', 'RUNNING')
        """,
    ),
    (
        "training_runs",
        """
        SELECT COUNT(*)
        FROM dbo.training_runs
        WHERE status IN ('PENDING', 'RUNNING')
        """,
    ),
    (
        "production_monitoring_runs",
        """
        SELECT COUNT(*)
        FROM dbo.production_monitoring_runs
        WHERE status = 'RUNNING'
        """,
    ),
)


class DemoResetDisabledError(RuntimeError):
    """Demo Reset chưa được bật bằng biến môi trường."""


class DemoResetBusyError(RuntimeError):
    """Một pipeline/training/monitoring job vẫn đang hoạt động."""


class DemoResetConfirmationError(ValueError):
    """Cụm xác nhận reset không chính xác."""


def demo_reset_enabled() -> bool:
    value = os.getenv("V2_DEMO_RESET_ENABLED", "")
    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class DemoResetService:
    """Reset dữ liệu nghiệp vụ phục vụ trình diễn.

    Mặc định chức năng bị vô hiệu hóa.

    Reset chỉ được commit khi:
    - V2_DEMO_RESET_ENABLED=true;
    - người dùng nhập đúng confirmation phrase;
    - không có pipeline/training/monitoring đang chạy;
    - toàn bộ DELETE hoàn thành trong cùng một transaction.

    schema_migrations và departments luôn được giữ lại.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or create_sql_engine()

    @staticmethod
    def _table_counts(conn: Connection) -> dict[str, int]:
        counts: dict[str, int] = {}

        for table_name in RESET_DELETE_ORDER:
            value = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM dbo.{table_name}
                    """
                )
            ).scalar_one()

            counts[table_name] = int(value)

        return counts

    @staticmethod
    def _retained_counts(conn: Connection) -> dict[str, int]:
        departments = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dbo.departments
                """
            )
        ).scalar_one()

        migrations = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dbo.schema_migrations
                """
            )
        ).scalar_one()

        return {
            "departments": int(departments),
            "schema_migrations": int(migrations),
        }

    @staticmethod
    def _busy_counts(conn: Connection) -> dict[str, int]:
        result: dict[str, int] = {}

        for name, sql in BUSY_QUERIES:
            count = conn.execute(text(sql)).scalar_one()
            result[name] = int(count)

        return result

    def status(self) -> dict[str, Any]:
        """Read-only trạng thái hiện tại của Demo Reset."""

        with self._engine.connect() as conn:
            counts = self._table_counts(conn)
            retained = self._retained_counts(conn)
            busy = self._busy_counts(conn)

        return {
            "enabled": demo_reset_enabled(),
            "confirmation_phrase": DEMO_RESET_CONFIRMATION,
            "clean": all(value == 0 for value in counts.values()),
            "busy": any(value > 0 for value in busy.values()),
            "busy_counts": busy,
            "counts": counts,
            "retained": retained,
        }

    def reset(
        self,
        *,
        confirmation: str,
    ) -> dict[str, Any]:
        """Xóa toàn bộ operational/demo state trong một transaction."""

        if not demo_reset_enabled():
            raise DemoResetDisabledError(
                "Demo Reset đang bị khóa. "
                "Phải bật V2_DEMO_RESET_ENABLED=true trước khi sử dụng."
            )

        if confirmation != DEMO_RESET_CONFIRMATION:
            raise DemoResetConfirmationError(
                "Confirmation phrase không chính xác."
            )

        with self._engine.begin() as conn:
            busy = self._busy_counts(conn)

            if any(value > 0 for value in busy.values()):
                raise DemoResetBusyError(
                    "Không thể reset khi Pipeline, Training hoặc Monitoring "
                    f"đang hoạt động: {busy}"
                )

            before = self._table_counts(conn)
            retained_before = self._retained_counts(conn)

            for table_name in RESET_DELETE_ORDER:
                conn.execute(
                    text(
                        f"""
                        DELETE FROM dbo.{table_name}
                        """
                    )
                )

            after = self._table_counts(conn)
            retained_after = self._retained_counts(conn)

            not_empty = {
                table_name: count
                for table_name, count in after.items()
                if count != 0
            }

            if not_empty:
                raise RuntimeError(
                    "Demo Reset verification failed. "
                    f"Tables còn dữ liệu: {not_empty}"
                )

            if retained_after != retained_before:
                raise RuntimeError(
                    "Demo Reset attempted to modify retained reference data. "
                    f"before={retained_before}, after={retained_after}"
                )

        return {
            "status": "RESET_COMPLETED",
            "clean": True,
            "before": before,
            "after": after,
            "retained": retained_after,
        }
