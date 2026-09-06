"""Emit machine-readable baseline results; returns 1 for product failures, 2 for harness errors."""

import argparse
import json
import sys
from pathlib import Path

from tests.rr.runtime.cases import CASES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rr-repo", required=True, type=Path, help="Read-only production source root"
    )
    parser.add_argument("--case", action="append", choices=list(CASES), dest="selected")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON only inside this RR runtime evidence directory",
    )
    args = parser.parse_args()
    results = []
    errors = []
    for name in args.selected or list(CASES):
        try:
            results.append(CASES[name](args.rr_repo.resolve()).document())
        except Exception as exc:
            errors.append(
                {
                    "case": name,
                    "kind": "harness_error",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    failed = sum(not entry["passed"] for entry in results)
    report = {
        "schema": "slink-rr-regression-probe-v1",
        "repo": str(args.rr_repo.resolve()),
        "simulator": "Lupa synthetic BizHawk host; no native ARM execution",
        "cases": results,
        "errors": errors,
        "summary": {
            "product_cases": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "harness_errors": len(errors),
        },
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        target = args.output.resolve()
        root = Path(__file__).resolve().parent
        if not target.is_relative_to(root):
            parser.error("--output must remain inside the RR runtime evidence directory")
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if errors else 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
