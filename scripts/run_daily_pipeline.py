from __future__ import annotations

import argparse
import json

from src.services.daily_pipeline_service import (
    run_daily_excel_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run V2 Daily Data Pipeline "
            "to DATA_READY using current "
            "Excel source adapter."
        )
    )

    parser.add_argument(
        "--noi",
        required=True,
        help="Path to HSNoi.xlsx",
    )

    parser.add_argument(
        "--ngoai",
        required=True,
        help="Path to hsNgoai.xlsx",
    )

    args = parser.parse_args()

    result = run_daily_excel_pipeline(
        args.noi,
        args.ngoai,
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
        if result.get("status")
        == "DATA_READY"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())