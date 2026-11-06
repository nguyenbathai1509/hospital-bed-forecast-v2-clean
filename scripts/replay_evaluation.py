from __future__ import annotations

import argparse
import json

from src.evaluation.service import replay_training_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay immutable row-level TEST evaluation evidence for a COMPLETED Training Run."
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    result = replay_training_evaluation(args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()