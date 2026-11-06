from __future__ import annotations

import argparse
from datetime import date
import json

from src.forecast.service import create_production_drafts


def _date(value: str | None):
    return None if value is None else date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-17 Production Predict. Creates/reuses DRAFT forecasts only; "
            "it never creates Official rows or daily model locks."
        )
    )

    parser.add_argument("--origin-date", default=None)
    parser.add_argument("--departments", nargs="+", type=int, default=None)
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 3])
    parser.add_argument("--created-by", default="manual")

    args = parser.parse_args()

    result = create_production_drafts(
        origin_date=_date(args.origin_date),
        department_ids=args.departments,
        horizons=args.horizons,
        created_by=args.created_by,
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