from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.training.config import (
    DEFAULT_RANDOM_SEED,
)

from src.training.service import (
    DEFAULT_ARTIFACT_ROOT,
    run_training,
)

from src.recommendation.service import (
    generate_recommendations,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run V2-14 Training Service "
            "for RF/XGBoost/SVR/LSTM "
            "on H+1 and H+3."
        )
    )

    parser.add_argument(
        "--triggered-by",
        default="manual",
        help=(
            "Audit label for who/what "
            "triggered this Training Run."
        ),
    )

    parser.add_argument(
        "--random-seed",
        type=int,
        default=(
            DEFAULT_RANDOM_SEED
        ),
    )

    parser.add_argument(
        "--artifact-root",
        default=str(
            DEFAULT_ARTIFACT_ROOT
        ),
    )

    args = parser.parse_args()

    result = run_training(
        triggered_by=(
            args.triggered_by
        ),
        random_seed=(
            args.random_seed
        ),
        artifact_root=Path(
            args.artifact_root
        ),
    )

    if result.get(
        "status"
    ) in {
        "COMPLETED",
        "ALREADY_COMPLETED",
    }:
        result[
            "recommendation"
        ] = (
            generate_recommendations(
                run_id=result[
                    "run_id"
                ]
            )
        )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    return (
        0
        if result[
            "status"
        ] in {
            "COMPLETED",
            "ALREADY_COMPLETED",
        }
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )