from __future__ import annotations

import argparse
import json

from src.promotion.service import (
    execute_promotion,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-16 Production Promotion. "
            "Without the exact confirmation phrase, "
            "the command returns a read-only plan "
            "and performs no database change."
        )
    )

    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 3],
        help=(
            "Horizons to promote from current "
            "Recommendation. Default: 1 3."
        ),
    )

    parser.add_argument(
        "--confirm",
        default=None,
    )

    parser.add_argument(
        "--requested-by",
        default="manual",
    )

    parser.add_argument(
        "--reason",
        default=(
            "Promote recommended model(s) "
            "to Production."
        ),
    )

    args = parser.parse_args()

    result = execute_promotion(
        horizons=args.horizons,
        confirmation=args.confirm,
        requested_by=args.requested_by,
        reason=args.reason,
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