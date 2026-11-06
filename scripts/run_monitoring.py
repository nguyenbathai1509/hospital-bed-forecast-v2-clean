from __future__ import annotations

import argparse
import json

from src.monitoring.service import (
    run_monitoring_cycle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2-18 Actual Matching + Production Monitoring. "
            "Only Official Forecasts are eligible; "
            "future Actual is never fabricated."
        )
    )

    parser.add_argument(
        "--pipeline-run-id",
        default=None,
        help=(
            "Optional existing pipeline run to attach "
            "the monitoring snapshot to. "
            "Default: latest DATA_READY run."
        ),
    )

    args = parser.parse_args()

    result = run_monitoring_cycle(
        pipeline_run_id=(
            args.pipeline_run_id
        ),
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