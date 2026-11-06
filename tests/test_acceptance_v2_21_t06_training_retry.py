from datetime import date

import src.api.training_jobs as training_jobs


FAILED_JOB_ID = "TJOB_FAILED_OLD"
RETRY_JOB_ID = "TJOB_RETRY_NEW"


class _FakeBegin:
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
    def begin(self):
        return _FakeBegin()


class _FakeRepository:
    def recover_stale_running_jobs(self, *, stale_after_seconds):
        return []

    inserted = []
    reusable_calls = []

    # Job FAILED cũ chỉ được giữ làm audit.
    historical_failed_job = {
        "job_id": FAILED_JOB_ID,
        "business_date": date(2026, 6, 30),
        "status": "FAILED",
        "error_message": "simulated previous failure",
    }

    def __init__(self, conn):
        self.conn = conn

    def latest_data_ready_context(self):
        return {
            "run_id": "DAY_READY_TEST",
            "business_date": date(2026, 6, 30),
            "data_version": "test",
        }

    def reusable_job_for_business_date(
        self,
        business_date,
    ):
        self.__class__.reusable_calls.append(
            business_date
        )

        # Đúng contract repository:
        # FAILED không được reuse.
        return None

    def insert_pending_job(
        self,
        **kwargs,
    ):
        self.__class__.inserted.append(
            kwargs
        )


def test_t06_failed_training_job_creates_new_retry_job(
    monkeypatch,
):
    _FakeRepository.inserted = []
    _FakeRepository.reusable_calls = []

    old_failed = dict(
        _FakeRepository.historical_failed_job
    )

    monkeypatch.setattr(
        training_jobs,
        "create_sql_engine",
        lambda: _FakeEngine(),
    )

    monkeypatch.setattr(
        training_jobs,
        "TrainingJobRepository",
        _FakeRepository,
    )

    monkeypatch.setattr(
        training_jobs,
        "_new_job_id",
        lambda: RETRY_JOB_ID,
    )

    service = (
        training_jobs.TrainingJobService()
    )

    result = service.start_job(
        requested_by="operator",
        random_seed=42,
    )

    assert result["job_id"] == RETRY_JOB_ID
    assert result["job_id"] != FAILED_JOB_ID

    assert result["business_date"] == date(
        2026, 6, 30
    )

    assert (
        result["source_pipeline_run_id"]
        == "DAY_READY_TEST"
    )

    assert result["status"] == "PENDING"
    assert result["training_run_id"] is None

    assert result["reused"] is False
    assert result["should_schedule"] is True

    assert (
        _FakeRepository.reusable_calls
        == [date(2026, 6, 30)]
    )

    assert len(
        _FakeRepository.inserted
    ) == 1

    inserted = (
        _FakeRepository.inserted[0]
    )

    assert inserted["job_id"] == RETRY_JOB_ID
    assert inserted["business_date"] == date(
        2026, 6, 30
    )

    assert (
        inserted["source_pipeline_run_id"]
        == "DAY_READY_TEST"
    )

    assert inserted["requested_by"] == "operator"
    assert inserted["random_seed"] == 42

    # FAILED job cũ vẫn nguyên trạng để audit.
    assert (
        _FakeRepository.historical_failed_job
        == old_failed
    )
