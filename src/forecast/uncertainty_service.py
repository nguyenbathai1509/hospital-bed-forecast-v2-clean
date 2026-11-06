"""Read-only interval lookup, separate from Preview/Draft/Official lifecycle."""
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from src.db.engine import create_sql_engine
from src.forecast.uncertainty import LOOKBACK_DAYS, build_uncertainty


class UncertaintyRepository:
    def __init__(self, conn):
        self.conn = conn

    def candidate(self, candidate_id):
        row = self.conn.execute(text("""
            SELECT mc.candidate_id, mc.horizon, tr.data_end
            FROM dbo.model_candidates mc
            JOIN dbo.training_runs tr ON tr.run_id=mc.run_id
            WHERE mc.candidate_id=:candidate_id AND tr.status='COMPLETED'
        """), {"candidate_id": candidate_id}).mappings().first()
        return None if row is None else dict(row)

    def calibration_rows(self, *, candidate_id, department_id, horizon, origin_date):
        # Timestamp and out-of-training checks are repeated in the pure function,
        # with the exact as-of cutoff. No backtest/refitted-model residuals here.
        rows = self.conn.execute(text("""
            SELECT ofc.official_id, ofc.candidate_id, ofc.department_id, ofc.horizon,
                   ofc.origin_date, ofc.target_date, ofc.prediction_raw, ofc.issued_at,
                   m.actual_occupied_beds, m.actual_quality_flag,
                   m.actual_source_revision_no, m.match_revision_no, m.last_refreshed_at
            FROM dbo.official_forecasts ofc
            JOIN dbo.official_actual_matches m ON m.official_id=ofc.official_id
            WHERE ofc.candidate_id=:candidate_id AND ofc.department_id=:department_id
              AND ofc.horizon=:horizon AND ofc.target_date BETWEEN :start_date AND :origin_date
              AND ofc.origin_date < :origin_date
            ORDER BY ofc.target_date, ofc.official_id
        """), {"candidate_id": candidate_id, "department_id": department_id,
               "horizon": horizon, "origin_date": origin_date,
               "start_date": origin_date - timedelta(days=min(LOOKBACK_DAYS - 1, origin_date.toordinal() - 1))}).mappings().all()
        return [dict(row) for row in rows]


class UncertaintyService:
    def calculate(self, **request) -> dict:
        engine = create_sql_engine()
        try:
            with engine.connect() as conn:
                repo = UncertaintyRepository(conn)
                candidate = repo.candidate(request["candidate_id"])
                if candidate is None:
                    raise ValueError("Không tìm thấy mô hình thuộc lần huấn luyện đã hoàn thành.")
                if int(candidate["horizon"]) != request["horizon"]:
                    raise ValueError("Mô hình không khớp mốc dự báo.")
                rows = repo.calibration_rows(**{key: request[key] for key in
                    ("candidate_id", "department_id", "horizon", "origin_date")})
            return build_uncertainty(**request, rows=rows,
                training_data_end=candidate["data_end"], now=datetime.now(timezone.utc))
        finally:
            engine.dispose()
