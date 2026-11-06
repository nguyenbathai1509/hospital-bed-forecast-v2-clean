from __future__ import annotations

import argparse
import json

from src.recommendation.service import (
    generate_recommendations,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate V2-15 dynamic model recommendations "
            "for H+1 and H+3. "
            "This command never promotes Production."
        )
    )

    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Training Run ID. "
            "Default: latest COMPLETED Training Run."
        ),
    )

    args = parser.parse_args()

    result = (
        generate_recommendations(
            run_id=args.run_id
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

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )