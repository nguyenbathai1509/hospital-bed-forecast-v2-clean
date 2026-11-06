from __future__ import annotations

import argparse
import json

from src.promotion.service import (
    execute_emergency_rollback,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-16 audited emergency rollback. "
            "The command requires an exact strong "
            "confirmation phrase and never rewrites "
            "previously issued Official Forecasts."
        )
    )

    parser.add_argument(
        "--horizon",
        type=int,
        required=True,
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
        required=True,
    )

    args = parser.parse_args()

    result = (
        execute_emergency_rollback(
            horizon=args.horizon,
            confirmation=args.confirm,
            requested_by=args.requested_by,
            reason=args.reason,
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