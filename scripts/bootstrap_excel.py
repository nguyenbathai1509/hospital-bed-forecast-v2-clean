from __future__ import annotations

import argparse
import json

from src.services.bootstrap_service import bootstrap_excel_to_sql


def main() -> None:
    p = argparse.ArgumentParser(description="One-time V2 bootstrap from the two hospital Excel exports into local SQL Server.")
    p.add_argument("--noi", required=True, help="Path to HSNoi.xlsx")
    p.add_argument("--ngoai", required=True, help="Path to hsNgoai.xlsx")
    args = p.parse_args()
    result = bootstrap_excel_to_sql([args.noi, args.ngoai])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] == "FAILED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
