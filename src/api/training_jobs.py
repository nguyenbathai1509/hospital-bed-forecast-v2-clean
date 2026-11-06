from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.db.engine import create_sql_engine
from src.evaluation.repository import EvaluationRepository
from src.evaluation.service import (
    replay_training_evaluation,
)
from src.recommendation.service import generate_recommendations
from src.training.config import DEFAULT_RANDOM_SEED
from src.training.service import run_training
from src.training.job_context import (
    TrainingJobLeaseLost, fence_training_job, link_training_run, training_job_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TRAINING_JOB_HEARTBEAT_INTERVAL_SECONDS = 15
TRAINING_JOB_STALE_AFTER_SECONDS = 120
TRAINING_JOB_LOG_DIR = PROJECT_ROOT / "reports" / "training_jobs"

logger = logging.getLogger(__name__)


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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class TrainingJobRepository:
    """Small write repository dedicated to persistent API training jobs.

    The scientific Training Run remains dbo.training_runs and is still created/updated
    only by V2-14 Training Service.  This repository owns only dbo.api_training_jobs.
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

    def reusable_job_for_business_date(self, business_date) -> dict | None:
        """Lock the business-date job range and reuse active/completed work.

        UPDLOCK + HOLDLOCK keeps two near-simultaneous POST requests from both creating
        a new active job for the same business date in the current single-database V2
        deployment. FAILED jobs are deliberately not reused so Retry remains possible.
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
            {"business_date": business_date},
        ).mappings().first()

        return None if row is None else dict(row)

    def evaluation_prediction_count(self, training_run_id: str) -> int:
        return int(
            self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dbo.model_evaluation_predictions
                    WHERE run_id=:run_id
                    """
                ),
                {"run_id": training_run_id},
            ).scalar_one()
        )

    def evaluation_evidence_complete(self, training_run_id: str) -> bool:
        return EvaluationRepository(self.conn).evaluation_evidence_complete(training_run_id)

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

    def claim_job(self, job_id: str) -> dict | None:
        row = self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs WITH (UPDLOCK, ROWLOCK)
                SET
                    status='RUNNING',
                    started_at=COALESCE(started_at, SYSUTCDATETIME()),
                    heartbeat_at=SYSUTCDATETIME(),
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
                WHERE job_id=:job_id AND status='PENDING'
                """
            ),
            {"job_id": job_id},
        ).mappings().first()

        return None if row is None else dict(row)

    def touch_heartbeat(self, job_id: str) -> bool:
        row = self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET heartbeat_at=SYSUTCDATETIME()
                OUTPUT inserted.job_id
                WHERE job_id=:job_id AND status='RUNNING'
                """
            ),
            {"job_id": job_id},
        ).mappings().first()
        return row is not None

    def recover_stale_running_jobs(
        self,
        *,
        stale_after_seconds: int,
    ) -> list[dict]:
        """Fail expired RUNNING jobs and PENDING jobs never claimed by a worker.

        heartbeat_at is authoritative for heartbeat-aware workers.
        started_at is the compatibility fallback for RUNNING jobs created
        before heartbeat support was introduced.
        """

        if stale_after_seconds <= 0:
            raise ValueError(
                "stale_after_seconds must be greater than 0"
            )

        rows = self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs WITH (UPDLOCK, ROWLOCK)
                SET
                    status='FAILED',
                    error_message=CASE WHEN status='PENDING'
                        THEN 'WORKER_STALE: worker did not claim pending job'
                        ELSE 'WORKER_STALE: heartbeat expired' END,
                    completed_at=SYSUTCDATETIME()
                OUTPUT
                    inserted.job_id,
                    inserted.training_run_id
                WHERE
                    (status='RUNNING'
                    AND COALESCE(heartbeat_at, started_at)
                        < DATEADD(
                            second,
                            -:stale_after_seconds,
                            SYSUTCDATETIME()
                        ))
                    OR (status='PENDING' AND created_at
                        < DATEADD(second, -:stale_after_seconds, SYSUTCDATETIME()))
                """
            ),
            {
                "stale_after_seconds": int(
                    stale_after_seconds
                )
            },
        ).mappings().all()

        recovered = [
            dict(row)
            for row in rows
        ]

        for row in recovered:
            training_run_id = row.get(
                "training_run_id"
            )

            if not training_run_id:
                continue

            self.conn.execute(
                text(
                    """
                    UPDATE dbo.training_runs
                    SET
                        status='FAILED',
                        completed_at=SYSUTCDATETIME(),
                        error_message='WORKER_STALE: API Training Job heartbeat expired'
                    WHERE run_id=:training_run_id AND status='RUNNING'
                    """
                ),
                {
                    "training_run_id": str(
                        training_run_id
                    )
                },
            )

        return recovered

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
                WHERE job_id=:job_id AND status='RUNNING'
                """
            ),
            {
                "job_id": job_id,
                "training_run_id": training_run_id,
                "result_json": _json_dump(result),
            },
        )

    def finish_failed(self, *, job_id: str, error_message: str) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET
                    status='FAILED',
                    error_message=:error_message,
                    completed_at=SYSUTCDATETIME()
                WHERE job_id=:job_id AND status='RUNNING'
                """
            ),
            {
                "job_id": job_id,
                "error_message": error_message[:4000],
            },
        )

    def fail_pending_job(self, *, job_id: str, error_message: str) -> None:
        self.conn.execute(
            text(
                """
                UPDATE dbo.api_training_jobs
                SET
                    status='FAILED',
                    error_message=:error_message,
                    completed_at=SYSUTCDATETIME()
                WHERE job_id=:job_id AND status='PENDING'
                """
            ),
            {
                "job_id": job_id,
                "error_message": error_message[:4000],
            },
        )


def _execute_training_workflow(
    *,
    requested_by: str,
    random_seed: int,
    job_id: str | None = None,
    engine=None,
) -> tuple[str, dict]:
    """Run the verified Training -> Recommendation -> Evaluation workflow.

    Evaluation Replay is part of Training Job completion from V2-20A onward. If the
    replay fails, the API job fails, while the already-COMPLETED scientific Training
    Run remains untouched. Retrying is safe because V2-14 and V2-15 are idempotent.
    """

    if job_id is not None:
        with engine.begin() as conn:
            fence_training_job(conn)
    logger.info("Training stage started")
    training_result = run_training(
        triggered_by=f"api:{requested_by}",
        random_seed=int(random_seed),
    )

    if training_result.get("status") not in {
        "COMPLETED",
        "ALREADY_COMPLETED",
    }:
        raise RuntimeError(
            "Training Service returned a non-terminal success status: "
            f"{training_result.get('status')}"
        )

    training_run_id = str(training_result["run_id"])

    if job_id is not None:
        with engine.begin() as conn:
            fence_training_job(conn)
            # Also link an ALREADY_COMPLETED run reused after a replay failure.
            link_training_run(conn, training_run_id)

    logger.info("Recommendation stage started for %s", training_run_id)
    recommendation_result = generate_recommendations(
        run_id=training_run_id
    )

    if job_id is not None:
        with engine.begin() as conn:
            fence_training_job(conn)
    logger.info("Evaluation stage started for %s", training_run_id)
    evaluation_result = replay_training_evaluation(
        training_run_id
    )

    if evaluation_result.get("status") not in {
        "COMPLETED",
        "ALREADY_REPLAYED",
    }:
        raise RuntimeError(
            "Evaluation Replay returned a non-terminal success status: "
            f"{evaluation_result.get('status')}"
        )

    result = {
        "training": training_result,
        "recommendation": recommendation_result,
        "evaluation": evaluation_result,
    }

    return training_run_id, result


def _heartbeat_loop(
    *,
    engine,
    job_id: str,
    stop_event,
    interval_seconds: int,
) -> None:
    """Refresh one RUNNING Training Job heartbeat until stopped."""

    if interval_seconds <= 0:
        raise ValueError(
            "interval_seconds must be greater than 0"
        )

    while not stop_event.wait(interval_seconds):
        try:
            # Never share the workflow connection with the heartbeat thread.
            # Every heartbeat uses its own short transaction scope.
            with engine.begin() as conn:
                active = TrainingJobRepository(conn).touch_heartbeat(
                    job_id
                )
            if active is False:
                logger.warning("Worker lease no longer active for %s", job_id)
                return
        except Exception:
            # A transient database error must not permanently kill the
            # heartbeat loop. A later tick can recover naturally.
            logger.exception(
                "Training Job heartbeat refresh failed for %s",
                job_id,
            )


class TrainingJobService:
    """Persistent asynchronous wrapper around V2-14 + V2-15.

    FastAPI returns the job id before model training runs.  The background task calls
    run_job(), which delegates all scientific work to the existing verified services.
    """

    def start_job(
        self,
        *,
        requested_by: str = "api",
        random_seed: int = DEFAULT_RANDOM_SEED,
    ) -> dict:
        requested_by = requested_by.strip()
        if not requested_by:
            raise ValueError("requested_by must not be blank")
        if random_seed < 0:
            raise ValueError("random_seed must be >= 0")

        engine = create_sql_engine()

        with engine.begin() as conn:
            repo = TrainingJobRepository(conn)
            ready = repo.latest_data_ready_context()
            if ready is None:
                raise NoDataReadyError(
                    "No DATA_READY Daily Pipeline run exists; training cannot start"
                )

            recovered = repo.recover_stale_running_jobs(
                stale_after_seconds=TRAINING_JOB_STALE_AFTER_SECONDS,
            )
            if recovered:
                logger.warning("Recovered expired training jobs: %s", recovered)
            existing = repo.reusable_job_for_business_date(ready["business_date"])
            if existing is not None:
                reusable = True

                # A COMPLETED API job created before V2-20A may point to a valid
                # COMPLETED Training Run but have no row-level evaluation evidence.
                # In that case, create a lightweight retry job. run_training() and
                # recommendation generation are idempotent and return ALREADY_*; only
                # Evaluation Replay needs to execute.
                if (
                    existing["status"] == "COMPLETED"
                    and existing.get("training_run_id")
                ):
                    reusable = repo.evaluation_evidence_complete(
                        str(existing["training_run_id"])
                    )

                if reusable:
                    return {
                        **existing,
                        "reused": True,
                        "should_schedule": False,
                    }

            job_id = _new_job_id()
            repo.insert_pending_job(
                job_id=job_id,
                business_date=ready["business_date"],
                source_pipeline_run_id=str(ready["run_id"]),
                requested_by=requested_by,
                random_seed=random_seed,
            )

            return {
                "job_id": job_id,
                "business_date": ready["business_date"],
                "source_pipeline_run_id": str(ready["run_id"]),
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

    def mark_launch_failed(self, job_id: str, exc: Exception) -> None:
        engine = create_sql_engine()
        message = f"WORKER_LAUNCH_FAILED: {type(exc).__name__}: {exc}"
        with engine.begin() as conn:
            TrainingJobRepository(conn).fail_pending_job(
                job_id=job_id,
                error_message=message,
            )

    def run_job(self, job_id: str) -> None:
        """Execute one claimed job in the dedicated worker process."""

        engine = create_sql_engine()

        with engine.begin() as conn:
            claimed = TrainingJobRepository(conn).claim_job(job_id)

        if claimed is None:
            # Idempotency: a duplicate background call cannot re-run a non-PENDING job.
            return

        stop_event = Event()
        heartbeat = Thread(
            target=_heartbeat_loop,
            kwargs={
                "engine": engine, "job_id": job_id, "stop_event": stop_event,
                "interval_seconds": TRAINING_JOB_HEARTBEAT_INTERVAL_SECONDS,
            },
            name=f"heartbeat-{job_id}", daemon=True,
        )
        heartbeat_started = False
        try:
            heartbeat.start()
            heartbeat_started = True
            logger.info("Worker claimed %s", job_id)
            with training_job_context(job_id):
                training_run_id, result = _execute_training_workflow(
                    requested_by=str(claimed["requested_by"]),
                    random_seed=int(claimed["random_seed"]),
                    job_id=job_id, engine=engine,
                )
                with engine.begin() as conn:
                    fence_training_job(conn)
                    TrainingJobRepository(conn).finish_completed(
                        job_id=job_id,
                        training_run_id=training_run_id,
                        result=result,
                    )
            logger.info("Worker completed %s", job_id)

        except TrainingJobLeaseLost:
            # Recovery owns the terminal state. Never replace it with late results.
            logger.warning("Worker stopped publishing after lease loss: %s", job_id)
        except Exception as exc:
            logger.exception("Worker failed: %s", job_id)
            message = f"{type(exc).__name__}: {exc}"
            with engine.begin() as conn:
                TrainingJobRepository(conn).finish_failed(
                    job_id=job_id,
                    error_message=message,
                )
        finally:
            stop_event.set()
            if heartbeat_started:
                heartbeat.join(timeout=5)
                if heartbeat.is_alive():
                    logger.warning("Heartbeat DB call still finishing for %s", job_id)


class TrainingJobLauncher:
    """Launch one detached Python worker so long ML training does not block Uvicorn.

    The command is fixed; no client-supplied executable/module/path is accepted. The
    worker uses sys.executable, therefore it runs inside the same project virtualenv.
    """

    def launch(self, job_id: str) -> None:
        if re.fullmatch(r"TJOB_[A-Za-z0-9_-]{1,75}", job_id) is None:
            raise ValueError("Invalid training job id")
        command = [
            sys.executable,
            "-u",
            "-m",
            "scripts.run_training_job",
            "--job-id",
            job_id,
        ]

        kwargs = {
            "cwd": str(PROJECT_ROOT),
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }

        if sys.platform.startswith("win"):
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        TRAINING_JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Append to preserve diagnostics even if a launch is retried.
        with (TRAINING_JOB_LOG_DIR / f"{job_id}.log").open("ab") as log_file:
            subprocess.Popen(command, stdout=log_file, **kwargs)
