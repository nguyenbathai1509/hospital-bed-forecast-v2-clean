from __future__ import annotations

import argparse
import logging

from src.api.training_jobs import TrainingJobService


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description=(
            "Run one persistent V2-19 asynchronous "
            "Training Job worker."
        )
    )

    parser.add_argument(
        "--job-id",
        required=True,
    )

    args = parser.parse_args()

    try:
        TrainingJobService().run_job(args.job_id)
    except Exception:
        logging.getLogger(__name__).exception("Worker crashed: %s", args.job_id)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
