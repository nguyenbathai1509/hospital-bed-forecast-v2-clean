from __future__ import annotations

import argparse
from datetime import date
import json

from src.forecast.service import generate_preview


def _date(value: str | None):
    return None if value is None else date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-17 read-only forecast Preview. Preview is not Official, "
            "is not persisted, and is excluded from Production monitoring."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["PRODUCTION", "RECOMMENDED", "CUSTOM"],
        default="PRODUCTION",
    )

    parser.add_argument("--origin-date", default=None)
    parser.add_argument("--departments", nargs="+", type=int, default=None)
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 3])
    parser.add_argument("--candidate-h1", default=None)
    parser.add_argument("--candidate-h3", default=None)

    args = parser.parse_args()

    custom = {
        horizon: candidate
        for horizon, candidate in (
            (1, args.candidate_h1),
            (3, args.candidate_h3),
        )
        if candidate is not None
    }

    result = generate_preview(
        mode=args.mode,
        origin_date=_date(args.origin_date),
        department_ids=args.departments,
        horizons=args.horizons,
        custom_candidates=custom,
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
    raise SystemExit(main())