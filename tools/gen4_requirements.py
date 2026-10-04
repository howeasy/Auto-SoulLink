#!/usr/bin/env python3
"""Gen 4 C0 obligation bindings over the shared coverage_map validator.

This is a mapping inventory, not a gate runner. Check targets are PLANNED until
their separate implementation cards produce executable checks and receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from tools import coverage_map

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/gen4_requirements.md"
PLAN = ROOT / "docs/gen4/PLAN.md"
LOCK = ROOT / "data/gen4_sources.lock.json"
MANIFEST = ROOT / "tests/gen4_requirements.json"

ARTIFACTS = ("heartgold", "soulsilver", "heartgold_hge", "platinum")
RUN_ARTIFACTS = ARTIFACTS[:3]
DIRECTIONS = {
    "hg_to_ss": ("heartgold", "soulsilver"),
    "ss_to_hg": ("soulsilver", "heartgold"),
    "hge_to_hge": ("heartgold_hge",),
}
SIDE_ARTIFACTS = {
    "hg_to_ss": ("heartgold", "soulsilver"),
    "ss_to_hg": ("soulsilver", "heartgold"),
    "hge_to_hge": ("heartgold_hge", "heartgold_hge"),
}
FIXTURE_SLOTS = {
    "hg_to_ss": ("hg_a", "ss_b"),
    "ss_to_hg": ("ss_a", "hg_b"),
    "hge_to_hge": ("hge_a", "hge_b"),
}
FAMILIES = {
    "F": 7, "R": 6, "S": 8, "W": 7, "C": 4, "N": 1, "D": 11,
}
G1_ROWS = tuple("abcdefghijklmno")
NONPHYSICAL = {"F-7", "S-7", "S-8"}
SCENARIOS = {
    "D-1": "link", "D-2": "deadzone", "D-3": "linked_faint_active",
    "D-4": "faint_cmd", "D-5": "boxsync", "D-6": "whiteout",
    "D-7": "reconnect_wrong_save", "D-8": "clauses_shiny",
    "D-9": "gift_egg", "D-10": "doubles", "D-11": "npc_trade",
}
LAYERS = ("SOURCE", "MODEL", "PHYSICAL")


def _unique_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("JSON root must be an object")
    return result


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_ids() -> set[str]:
    return {f"{family}-{number}" for family, count in FAMILIES.items()
            for number in range(0 if family == "C" else 1, count + (0 if family == "C" else 1))}


def _ledger_rows(text: str) -> dict[str, tuple[str, ...]]:
    rows = {}
    for line in text.splitlines():
        match = re.match(r"^\| ((?:F|R|S|W|C|N|D)-\d+) \|", line)
        if not match:
            continue
        identifier = match.group(1)
        if identifier in rows:
            raise ValueError(f"duplicate ledger row: {identifier}")
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if len(cells) != 6 or any(not cell for cell in cells):
            raise ValueError(f"malformed ledger row: {identifier}")
        if cells[2:4] != ("OPEN", "OPEN") or cells[4] not in ("OPEN", "N/A D3", "N/A cited source", "LIMIT D14"):
            raise ValueError(f"ledger evidence is not initially OPEN/scoped: {identifier}")
        rows[identifier] = cells
    expected = _canonical_ids()
    if set(rows) != expected:
        raise ValueError(f"ledger inventory differs: missing={sorted(expected-set(rows))}, extra={sorted(set(rows)-expected)}")
    for identifier, expected_p in (("F-7", "N/A D3"), ("S-7", "N/A cited source"), ("S-8", "LIMIT D14")):
        if rows[identifier][4] != expected_p:
            raise ValueError(f"ledger physical policy changed: {identifier}")
    if any(rows[identifier][4] != "OPEN" for identifier in expected - NONPHYSICAL):
        raise ValueError("a required physical ledger cell was lowered")
    return rows


def _plan_g1(text: str) -> None:
    section = text.split("### 5.1 G1 probe rows", 1)
    if len(section) != 2:
        raise ValueError("G1 probe section missing")
    section = section[1].split("\n## ", 1)[0]
    found = re.findall(r"^\| ([a-o]) [^|]+ \|", section, re.M)
    if tuple(found) != G1_ROWS:
        raise ValueError(f"G1 a-o row inventory differs: {found}")


def _lock_artifacts(raw: bytes) -> dict[str, str]:
    lock = _unique_json(raw)
    if lock.get("schema_version") != 1 or not isinstance(lock.get("artifacts"), dict):
        raise ValueError("Gen4 lock schema_version=1/artifacts required")
    if set(lock["artifacts"]) != set(ARTIFACTS):
        raise ValueError("Gen4 lock must name exactly HG, SS, hge and Pt artifacts")
    artifacts = {}
    for name in ARTIFACTS:
        item = lock["artifacts"][name]
        if not isinstance(item, dict) or item.get("state") not in {"PINNED", "OPEN"}:
            raise ValueError(f"{name}: invalid lock state")
        digest = item.get("sha1")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{40}", digest) is None:
            raise ValueError(f"{name}: verified SHA1 required")
        if item["state"] != "PINNED":
            raise ValueError(f"{name}: OPEN artifact cannot supply verified binding digest")
        artifacts[name] = digest
    return artifacts


def _spec() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Independent, caller-owned policy; never inferred from mutable map rows."""
    result = {}
    for row in sorted(_canonical_ids()):
        if row.startswith("D-"):
            for direction, sides in DIRECTIONS.items():
                result[f"{row}:{direction}"] = (LAYERS, sides)
            continue
        if row == "F-7":
            scopes = ("platinum",)
        elif row == "R-6":
            scopes = ("heartgold_hge",)
        elif row == "F-1":
            scopes = ARTIFACTS
        else:
            scopes = RUN_ARTIFACTS
        for artifact in scopes:
            layers = (("SOURCE", "MODEL") if row in NONPHYSICAL and
                      not (row == "S-7" and artifact == "heartgold_hge")
                      else ("SOURCE", "MODEL") if artifact == "platinum" else LAYERS)
            result[f"{row}:{artifact}"] = (layers, (artifact,))
    for letter in G1_ROWS:
        for artifact in RUN_ARTIFACTS:
            result[f"G1-{letter}:{artifact}"] = (LAYERS, (artifact,))
    return result


def _descriptor(identifier: str, artifacts: dict[str, str]) -> tuple[dict, dict]:
    row, variant = identifier.split(":", 1)
    policy = _spec()[identifier]
    check_id = f"gen4.{row.lower().replace('-', '_')}.{variant}"
    case = f"test_{row.lower().replace('-', '_')}[{variant}]"
    physical_target = (f"tests/e2e/test_gen4_duo.py::test_{SCENARIOS[row]}[{variant}]"
                       if row.startswith("D-") else
                       f"tests/live/test_gen4_probe_gates.py::{case}"
                       if row.startswith("G1-") else
                       f"tests/live/test_gen4_{row[0].lower()}_gates.py::{case}")
    targets = {"SOURCE": f"tests/unit/test_gen4_source_oracles.py::{case}",
               "MODEL": f"tests/unit/test_gen4_model_oracles.py::{case}"}
    if "PHYSICAL" in policy[0]:
        targets["PHYSICAL"] = physical_target
    physical = "PHYSICAL" in policy[0]
    marker = f"GEN4_{row.replace('-', '_')}_{variant.upper()}"
    mapping = {
        "status": "MAPPED",
        "stimulus": {"kind": ("NATURAL" if row.startswith("D-") else "COMMAND") if physical else "MODEL",
                     "description": f"Planned {row} control on {variant}; no execution claim."},
        "artifacts": {name: artifacts[name] for name in policy[1]},
        "positive_control": f"{check_id}.positive",
        "refusal_control": f"{check_id}.refusal",
        "oracle": f"{check_id}.independent_oracle",
        "receipt_marker": marker,
        "lane": check_id,
    }
    check = {"id": check_id, "obligation_id": identifier, "state": "PLANNED",
             "targets": targets, "receipt_id": marker,
             "positive_id": mapping["positive_control"],
             "refusal_id": mapping["refusal_control"],
             "oracle_id": mapping["oracle"],
             "side_artifacts": list(SIDE_ARTIFACTS[variant]) if row.startswith("D-") else [],
             "fixture_slots": list(FIXTURE_SLOTS[variant]) if row.startswith("D-") else []}
    return mapping, check


def seed_document(ledger_raw: bytes, plan_raw: bytes, lock_raw: bytes) -> dict:
    _ledger_rows(ledger_raw.decode("utf-8"))
    _plan_g1(plan_raw.decode("utf-8"))
    artifacts = _lock_artifacts(lock_raw)
    rows, checks = [], []
    for identifier, (layers, _) in sorted(_spec().items()):
        mapping, check = _descriptor(identifier, artifacts)
        rows.append({"id": identifier, "required_layers": list(layers), "mapping": mapping,
                     "evidence": {layer: {"status": "OPEN", "reason": "Planned; no immutable gate receipt."}
                                  for layer in layers}})
        checks.append(check)
    return {"schema_version": 1,
            "input_sha256": {"requirements": _sha(ledger_raw), "plan": _sha(plan_raw), "artifact_policy": _sha(lock_raw)},
            "checks": checks, "rows": rows}


def validate_document(document: dict, ledger_raw: bytes, plan_raw: bytes, lock_raw: bytes,
                      *, mode: str = "mapping", read_receipt=None) -> dict:
    _ledger_rows(ledger_raw.decode("utf-8"))
    _plan_g1(plan_raw.decode("utf-8"))
    artifacts = _lock_artifacts(lock_raw)
    spec = _spec()
    if not isinstance(document, dict) or set(document) != {"schema_version", "input_sha256", "checks", "rows"}:
        raise ValueError("unsupported Gen4 binding document")
    if document["schema_version"] != 1 or not isinstance(document["checks"], list):
        raise ValueError("unsupported Gen4 binding schema/check inventory")
    expected_checks = {_descriptor(identifier, artifacts)[1]["id"]: identifier for identifier in spec}
    seen = set()
    for check in document["checks"]:
        if not isinstance(check, dict) or set(check) != {"id", "obligation_id", "state", "targets", "receipt_id",
                                                     "positive_id", "refusal_id", "oracle_id",
                                                     "side_artifacts", "fixture_slots"}:
            raise ValueError("malformed planned check")
        cid = check["id"]
        if cid not in expected_checks or cid in seen or check["obligation_id"] != expected_checks[cid]:
            raise ValueError(f"unknown/duplicate/misbound check: {cid}")
        seen.add(cid)
        canonical = _descriptor(check["obligation_id"], artifacts)[1]
        if not isinstance(check["targets"], dict) or set(check["targets"]) != set(spec[check["obligation_id"]][0]):
            raise ValueError(f"missing/lowered evidence target: {cid}")
        if "PHYSICAL" in check["targets"] and check["targets"]["PHYSICAL"].startswith("tests/unit/"):
            raise ValueError(f"unit target cannot qualify PHYSICAL: {cid}")
        if check != canonical:
            raise ValueError(f"changed planned check binding: {cid}")
    if seen != set(expected_checks):
        raise ValueError(f"missing planned checks: {sorted(set(expected_checks)-seen)}")
    for row in document["rows"]:
        if isinstance(row, dict) and row.get("id") in spec:
            expected_mapping = _descriptor(row["id"], artifacts)[0]
            if row.get("mapping") != expected_mapping:
                raise ValueError(f"changed check/control/oracle binding: {row['id']}")
    obligations = {identifier: coverage_map.Obligation(layers, scopes)
                   for identifier, (layers, scopes) in spec.items()}
    inputs = {"requirements": _sha(ledger_raw), "plan": _sha(plan_raw), "artifact_policy": _sha(lock_raw)}
    coverage_doc = {key: document[key] for key in ("schema_version", "input_sha256", "rows")}
    report = coverage_map.validate_coverage(
        coverage_doc, obligations=obligations, artifacts=artifacts, inputs=inputs,
        read_receipt=read_receipt or (lambda _path: (_ for _ in ()).throw(FileNotFoundError("no receipt reader"))),
        mode=mode)
    if mode == "closure":
        report["errors"].append("planned check targets are not implemented/executed gate evidence")
        report["ok"] = False
    report["checks_planned"] = len(document["checks"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mapping", "closure", "inventory"), default="mapping")
    parser.add_argument("--seed", action="store_true", help="emit initial OPEN bindings, never gate evidence")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--lock", type=Path, default=LOCK)
    args = parser.parse_args(argv)
    try:
        raw = args.ledger.read_bytes(), args.plan.read_bytes(), args.lock.read_bytes()
        if args.seed:
            print(json.dumps(seed_document(*raw), indent=2) + "\n", end="")
            return 0
        document = _unique_json(args.manifest.read_bytes())
        report = validate_document(document, *raw, mode=args.mode)
        print(json.dumps({"ok": report["ok"], "mode": args.mode,
                          "mapping_complete": report["mapping_complete"],
                          "evidence_complete": report["evidence_complete"],
                          "obligations": report["obligations"],
                          "checks_planned": report["checks_planned"],
                          "open_counts": {layer: len(ids) for layer, ids in report["open"].items()},
                          "errors": report["errors"]}, indent=2))
        return 0 if report["ok"] else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
