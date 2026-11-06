from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.db.engine import create_sql_engine
from src.recommendation.service import generate_recommendations
from src.training.config import DEFAULT_RANDOM_SEED
from src.training.service import run_training


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TrainingJobError(RuntimeError):
    """Base error raised by the API training-job orchestration layer."""


class NoDataReadyError(TrainingJobError):
    """Raised when training cannot start because no DATA_READY pipeline exists."""


def _new_job_id() -> str:
    return (
        "TJOB_"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


def _json_dump(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


class TrainingJobRepository:
    """Small write repository dedicated to persistent API training jobs.

    The scientific Training Run remains dbo.training_runs and is still created/updated
    only by V2-14 Training Service. This repository owns only dbo.api_training_jobs.
    """

    def __init__(self, conn: Connection):
        self.conn = conn

    def latest_data_ready_context(self) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    run_id,
                    business_date,
                    data_version,
                    completed_at
                FROM dbo.pipeline_runs
                WHERE status='DATA_READY'
                ORDER BY completed_at DESC, started_at DESC
                """
            )
        ).mappings().first()

        return None if row is None else dict(row)

    def reusable_job_for_business_date(
        self,
        business_date,
    ) -> dict | None:
        """Lock the business-date job range and reuse active/completed work.

        UPDLOCK + HOLDLOCK keeps two near-simultaneous POST requests from both
        creating a new active job for the same business date in the current
        single-database V2 deployment.

        FAILED jobs are deliberately not reused so Retry remains possible.
        """

        row = self.conn.execute(
            text(
                """
                SELECT TOP 1
                    j.job_id,
                    j.business_date,
                    j.source_pipeline_run_id,
                    j.status,
                    j.requested_by,
                    j.random_seed,
                    j.training_run_id,
                    j.created_at,
                    j.started_at,
                    j.completed_at
                FROM dbo.api_training_jobs j WITH (UPDLOCK, HOLDLOCK)
                LEFT JOIN dbo.training_runs tr
                    ON tr.run_id=j.training_run_id
                WHERE
                    j.business_date=:business_date
                    AND (
                        j.status IN ('PENDING','RUNNING')
                        OR (
                            j.status='COMPLETED'
                            AND j.training_run_id IS NOT NULL
                            AND tr.status='COMPLETED'
                        )
                    )
                ORDER BY
                    CASE j.status
                        WHEN 'RUNNING' THEN 1
                        WHEN 'PENDING' THEN 2
                        ELSE 3
                    END,
                    j.created_at DESC
                """
            ),
            {
                "business_date": business_date,
            },
        ).mappings().first()

        return None if row is None else dict(row)

    def insert_pending_job(
        self,
        *,
        job_id: str,
        business_date,
        source_pipeline_run_id: str,
        requested_by: str,
        random_seed: int,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO dbo.api_training_jobs
                (
                    job_id,
                    business_date,
                    source_pipeline_run_id,
                    status,
                    requested_by,
                    random_seed,
                    created_at
                )
                VALUES
                (
                    :job_id,
                    :business_date,
                    :source_pipeline_run_id,
                    'PENDING',
                    :requested_by,
                    :random_seed,
                    SYSUTCDATETIME()
                )
                """
            ),
            {
                "job_id": job_id,
                "business_date": business_date,
                "source_pipeline_run_id": source_pipeline_run_id,
                "requested_by": requested_by,
                "random_seed": random_seed,
            },
        )

    def claim_job(
        self,
        job_id: str,
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs WITH (UPDLOCK, ROWLOCK)
                SET
                    status='RUNNING',
                    started_at=COALESCE(
                        started_at,
                        SYSUTCDATETIME()
                    ),
                    error_message=NULL
                OUTPUT
                    inserted.job_id,
                    inserted.business_date,
                    inserted.source_pipeline_run_id,
                    inserted.status,
                    inserted.requested_by,
                    inserted.random_seed,
                    inserted.training_run_id,
                    inserted.created_at,
                    inserted.started_at,
                    inserted.completed_at
                WHERE
                    job_id=:job_id
                    AND status='PENDING'
                """
            ),
            {
                "job_id": job_id,
            },
        ).mappings().first()

        return None if row is None else dict(row)

    def finish_completed(
        self,
        *,
        job_id: str,
        training_run_id: str,
        result: dict,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET
                    status='COMPLETED',
                    training_run_id=:training_run_id,
                    result_json=:result_json,
                    error_message=NULL,
                    completed_at=SYSUTCDATETIME()
                WHERE
                    job_id=:job_id
                    AND status='RUNNING'
                """
            ),
            {
                "job_id": job_id,
                "training_run_id": training_run_id,
                "result_json": _json_dump(result),
            },
        )

    def finish_failed(
        self,
        *,
        job_id: str,
        error_message: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET
                    status='FAILED',
                    error_message=:error_message,
                    completed_at=SYSUTCDATETIME()
                WHERE
                    job_id=:job_id
                    AND status='RUNNING'
                """
            ),
            {
                "job_id": job_id,
                "error_message": error_message[:4000],
            },
        )

    def fail_pending_job(
        self,
        *,
        job_id: str,
        error_message: str,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET
                    status='FAILED',
                    error_message=:error_message,
                    completed_at=SYSUTCDATETIME()
                WHERE
                    job_id=:job_id
                    AND status='PENDING'
                """
            ),
            {
                "job_id": job_id,
                "error_message": error_message[:4000],
            },
        )


class TrainingJobService:
    """Persistent asynchronous wrapper around V2-14 + V2-15.

    FastAPI returns the job id before model training runs. The worker calls
    run_job(), which delegates all scientific work to the existing verified
    services.
    """

    def start_job(
        self,
        *,
        requested_by: str = "api",
        random_seed: int = DEFAULT_RANDOM_SEED,
    ) -> dict:
        requested_by = requested_by.strip()

        if not requested_by:
            raise ValueError(
                "requested_by must not be blank"
            )

        if random_seed < 0:
            raise ValueError(
                "random_seed must be >= 0"
            )

        engine = create_sql_engine()

        with engine.begin() as conn:
            repo = TrainingJobRepository(conn)

            ready = repo.latest_data_ready_context()

            if ready is None:
                raise NoDataReadyError(
                    "No DATA_READY Daily Pipeline run exists; "
                    "training cannot start"
                )

            existing = repo.reusable_job_for_business_date(
                ready["business_date"]
            )

            if existing is not None:
                return {
                    **existing,
                    "reused": True,
                    "should_schedule": False,
                }

            job_id = _new_job_id()

            repo.insert_pending_job(
                job_id=job_id,
                business_date=ready["business_date"],
                source_pipeline_run_id=str(
                    ready["run_id"]
                ),
                requested_by=requested_by,
                random_seed=random_seed,
            )

            return {
                "job_id": job_id,
                "business_date": ready["business_date"],
                "source_pipeline_run_id": str(
                    ready["run_id"]
                ),
                "status": "PENDING",
                "requested_by": requested_by,
                "random_seed": random_seed,
                "training_run_id": None,
                "created_at": None,
                "started_at": None,
                "completed_at": None,
                "reused": False,
                "should_schedule": True,
            }

    def mark_launch_failed(
        self,
        job_id: str,
        exc: Exception,
    ) -> None:
        engine = create_sql_engine()

        message = (
            "WORKER_LAUNCH_FAILED: "
            f"{type(exc).__name__}: {exc}"
        )

        with engine.begin() as conn:
            TrainingJobRepository(
                conn
            ).fail_pending_job(
                job_id=job_id,
                error_message=message,
            )

    def run_job(
        self,
        job_id: str,
    ) -> None:
        """Execute one claimed job in the dedicated worker process."""

        engine = create_sql_engine()

        with engine.begin() as conn:
            claimed = TrainingJobRepository(
                conn
            ).claim_job(job_id)

        if claimed is None:
            # Idempotency:
            # duplicate worker call cannot re-run a non-PENDING job.
            return

        try:
            training_result = run_training(
                triggered_by=(
                    f"api:{claimed['requested_by']}"
                ),
                random_seed=int(
                    claimed["random_seed"]
                ),
            )

            if training_result.get("status") not in {
                "COMPLETED",
                "ALREADY_COMPLETED",
            }:
                raise RuntimeError(
                    "Training Service returned a "
                    "non-terminal success status: "
                    f"{training_result.get('status')}"
                )

            training_run_id = str(
                training_result["run_id"]
            )

            recommendation_result = (
                generate_recommendations(
                    run_id=training_run_id
                )
            )

            result = {
                "training": training_result,
                "recommendation": (
                    recommendation_result
                ),
            }

            with engine.begin() as conn:
                TrainingJobRepository(
                    conn
                ).finish_completed(
                    job_id=job_id,
                    training_run_id=training_run_id,
                    result=result,
                )

        except Exception as exc:
            message = (
                f"{type(exc).__name__}: {exc}"
            )

            with engine.begin() as conn:
                TrainingJobRepository(
                    conn
                ).finish_failed(
                    job_id=job_id,
                    error_message=message,
                )


class TrainingJobLauncher:
    """Launch one detached Python worker so long ML training
    does not block Uvicorn.

    The command is fixed; no client-supplied executable/module/path
    is accepted.

    The worker uses sys.executable, therefore it runs inside the same
    project virtualenv.
    """

    def launch(
        self,
        job_id: str,
    ) -> None:
        command = [
            sys.executable,
            "-m",
            "scripts.run_training_job",
            "--job-id",
            job_id,
        ]

        kwargs = {
            "cwd": str(PROJECT_ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }

        if sys.platform.startswith("win"):
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            command,
            **kwargs,
        )