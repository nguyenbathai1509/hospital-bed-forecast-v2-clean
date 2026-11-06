from __future__ import annotations

import argparse
from datetime import date
import json

from src.forecast.service import confirm_officials


def _date(value: str | None):
    return None if value is None else date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-17 Draft -> Official confirmation. Without the exact phrase, "
            "the command is read-only and only shows the open Draft plan."
        )
    )

    parser.add_argument("--origin-date", default=None)
    parser.add_argument("--confirm", default=None)
    parser.add_argument("--confirmed-by", default="manual")

    args = parser.parse_args()

    result = confirm_officials(
        confirmation=args.confirm,
        origin_date=_date(args.origin_date),
        confirmed_by=args.confirmed_by,
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