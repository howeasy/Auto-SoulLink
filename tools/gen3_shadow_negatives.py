"""Check cited expected-zero controls using the shared SHADOW semantic parser.

Counts are normalized kinds, not raw hook counts or independent transactions.
In particular pc_* sites become pc_move and poison contributes to both faint
and poison_faint, just as in the differential's coverage table. Positive rows
mean presence in this receipt, not callback/identity qualification. Predicate
logs have a separate log-format scope: silence cannot prove an armed hook.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

if __package__:
    from tools import gen3_shadow_diff as shadow_diff
else:
    import gen3_shadow_diff as shadow_diff


def _has_corresponding_event(diagnostic: dict, events: list) -> bool:
    """Check if a diagnostic has a corresponding event already counted.

    Unmatched completion diagnostics create both a diagnostic entry and an
    event; count the event once, not twice.
    """
    for event in events:
        if (event.kind == diagnostic["kind"] and
                event.key == diagnostic["key"] and
                event.sink == diagnostic["sink"]):
            return True
    return False

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / "docs/gen3/negatives_manifest.json"
SCOPES = {"observer", "observer_excerpt", "log_format_only"}


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("manifest needs schema=1")
    entries = data.get("receipts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest needs nonempty receipts")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("receipt must be an object")
        for field in ("file", "artifact", "why"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"receipt needs {field}")
        if entry.get("scope") not in SCOPES:
            raise ValueError("receipt needs an explicit evidence scope")
        if entry["file"] in seen:
            raise ValueError("duplicate receipt")
        seen.add(entry["file"])
        checks = entry.get("must_not")
        if not isinstance(checks, list) or not checks:
            raise ValueError("receipt needs nonempty must_not")
        kinds = set()
        for check in checks:
            if (not isinstance(check, dict) or check.get("kind") not in shadow_diff.KINDS
                    or not isinstance(check.get("why"), str) or not check["why"].strip()):
                raise ValueError("each check needs a semantic kind and cited why")
            if check["kind"] in kinds:
                raise ValueError("duplicate expected-zero kind")
            kinds.add(check["kind"])
    return entries


def check_manifest(path: Path, root: Path = REPO) -> dict:
    """Return all rows, continuing after missing/malformed receipts; no file writes."""
    manifest_data = json.loads(path.read_text(encoding="utf-8"))
    source_head = manifest_data.get("source_head", "")
    results = []
    for entry in load_manifest(path):
        result = {"file": entry["file"], "artifact": entry["artifact"],
                  "scope": entry["scope"], "why": entry["why"],
                  "positives": {}, "rows": [], "errors": []}
        counts = Counter()
        diagnostics = Counter()
        try:
            receipt = (root / entry["file"]).resolve()
            if not receipt.is_relative_to(root.resolve()):
                raise ValueError("receipt must stay within root")
            events = shadow_diff.reduce_shadow(receipt)
            counts.update(event.kind for event in events)
            # Use the same poison_faint derivation as gen3_shadow_diff.
            counts["poison_faint"] += sum(event.cause == "poison" for event in events)
            result["positives"] = {kind: count for kind, count in sorted(counts.items()) if count}
            # Only count diagnostics that don't have corresponding events.
            for diag in events.diagnostics:
                if not _has_corresponding_event(diag, events):
                    diagnostics[diag["kind"]] += 1
            result["diagnostics"] = events.diagnostics
            # ponytail: BLOCKER fix — only log_format_only may be empty
            if entry["scope"] in ("observer", "observer_excerpt") and not any(
                "SHADOW " in line for line in shadow_diff.read_text(receipt).splitlines()
            ):
                result["errors"].append("observer receipt must contain SHADOW records")
            # Also catch frame_control, which the semantic parser deliberately drops.
            if entry["scope"] == "log_format_only" and any(
                "SHADOW " in line for line in shadow_diff.read_text(receipt).splitlines()
            ):
                result["errors"].append("predicate-only log unexpectedly contains SHADOW lines")
        except (OSError, ValueError, KeyError, TypeError) as error:
            result["errors"].append(str(error))
        for check in entry["must_not"]:
            kind = check["kind"]
            # An unmatched forbidden begin must not disappear into normalization.
            count = counts[kind] + diagnostics[kind]
            result["rows"].append({"kind": kind, "count": count,
                                   "event_count": counts[kind],
                                   "diagnostic_count": diagnostics[kind],
                                   "passed": not result["errors"] and count == 0,
                                   "why": check["why"]})
        results.append(result)
    rows = [row for result in results for row in result["rows"]]
    failed = sum(not row["passed"] for row in rows)
    return {"passed": failed == 0 and not any(r["errors"] for r in results),
            "receipts": results, "summary": {"receipts": len(results), "checks": len(rows),
                                             "passed": len(rows) - failed, "failed": failed},
            "source_head": source_head}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=REPO,
                        help="root for receipt paths (default: repository, independent of cwd)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = check_manifest(args.manifest, args.root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {"passed": False, "error": str(error)}
    if args.json:
        print(json.dumps(report, indent=2))
    elif "error" in report:
        print(f"FAIL {report['error']}")
    else:
        source_head = report.get("source_head", "")
        if source_head:
            print(f"source_head: {source_head}")
        for receipt in report["receipts"]:
            label = f"{receipt['file']} [{receipt['artifact']}; {receipt['scope']}]"
            for kind, count in receipt["positives"].items():
                print(f"PRESENT {label} {kind} count={count}")
            if not receipt["positives"]:
                print(f"PRESENT {label} none")
            for row in receipt["rows"]:
                verdict = "PASS" if row["passed"] else "FAIL"
                print(f"EXPECTED-ZERO {verdict} {label} {row['kind']} count={row['count']}")
            for error in receipt["errors"]:
                print(f"ERROR {label} {error}")
        summary = report["summary"]
        verdict = "PASS" if report["passed"] else "FAIL"
        print(f"SUMMARY {verdict} receipts={summary['receipts']} checks={summary['checks']} "
              f"passed={summary['passed']} failed={summary['failed']}")
        print("Scope: normalized receipt counts; excerpts and log-format checks do not qualify hooks.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
