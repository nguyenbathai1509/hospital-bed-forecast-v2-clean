"""Optional write fence for training executed by a persistent API worker.

Direct/CLI training has no job context and keeps its existing behavior.
The job lock is held only for short write transactions, never while fitting.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import text


_job_id: ContextVar[str | None] = ContextVar("training_job_id", default=None)


class TrainingJobLeaseLost(RuntimeError):
    """The worker no longer owns a RUNNING job; it must not publish results."""


@contextmanager
def training_job_context(job_id: str):
    token = _job_id.set(job_id)
    try:
        yield
    finally:
        _job_id.reset(token)


def fence_training_job(conn) -> None:
    job_id = _job_id.get()
    if job_id is None:
        return
    status = conn.execute(
        text("""
            SELECT status FROM dbo.api_training_jobs WITH (UPDLOCK, HOLDLOCK)
            WHERE job_id=:job_id
        """),
        {"job_id": job_id},
    ).scalar_one_or_none()
    if status != "RUNNING":
        raise TrainingJobLeaseLost(f"Worker lease lost for {job_id}")


def link_training_run(conn, run_id: str) -> None:
    """Call inside the same fenced transaction that creates the run."""
    job_id = _job_id.get()
    if job_id is not None:
        conn.execute(
            text("""
                UPDATE dbo.api_training_jobs SET training_run_id=:run_id
                WHERE job_id=:job_id AND status='RUNNING'
            """),
            {"job_id": job_id, "run_id": run_id},
        )
