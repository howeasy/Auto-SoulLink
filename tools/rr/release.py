#!/usr/bin/env python3
"""Strict, standalone RR evidence verifier. Uses only Python's standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from contextlib import suppress
from datetime import datetime
from pathlib import Path, PureWindowsPath

if __package__:
    from .inventory import BASE_ROM_MD5, BINDING_ROLES, GROUPS, MODES, build_inventory
else:
    from inventory import BASE_ROM_MD5, BINDING_ROLES, GROUPS, MODES, build_inventory

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SCHEDULE_FIELDS = {
    "dispatch_offset_frames", "latency_ms", "pause_frames", "disconnect_at", "input_pattern"
}
DISCONNECT_PHASES = {"none", "before_stage", "after_stage", "after_apply", "before_readback", "after_receipt"}
INPUT_PATTERNS = {"neutral", "a_held", "b_held", "alternating_ab", "mash_a", "menu_navigation"}


def strict_json(text):
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON object key: {key}")
            out[key] = value
        return out
    def no_constant(value):
        raise ValueError(f"non-finite JSON number: {value}")
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed
    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=no_constant, parse_float=finite_float)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_int(value, minimum=0):
    return type(value) is int and value >= minimum


def verify(inventory, evidence, evidence_root):
    errors = []
    def error(code, location, message):
        errors.append({"code": code, "location": location, "message": message})
    def obj(value, location):
        if not isinstance(value, dict):
            error("schema.object", location, "expected an object")
            return {}
        return value
    def array(value, location):
        if not isinstance(value, list):
            error("schema.array", location, "expected an array")
            return []
        return value
    def equal(actual, expected, location, code="contract.mismatch"):
        if actual != expected or (isinstance(actual, bool) != isinstance(expected, bool)):
            error(code, location, f"expected {expected!r}; observed {actual!r}")
    def nonempty(value, location):
        if not isinstance(value, str) or not value.strip():
            error("schema.string", location, "expected a nonempty string")
            return False
        return True

    inv = obj(inventory, "inventory")
    ev = obj(evidence, "evidence")
    canonical = build_inventory()
    equal(inv.get("schema_version"), 1, "inventory.schema_version")
    equal(inv.get("modes"), list(MODES), "inventory.modes")
    equal(inv.get("groups"), list(GROUPS), "inventory.groups")
    core = {case["case_id"]: case for case in canonical["cases"]}
    supplied = {}
    for index, raw in enumerate(array(inv.get("cases"), "inventory.cases")):
        case = obj(raw, f"inventory.cases[{index}]")
        cid = case.get("case_id")
        if not nonempty(cid, f"inventory.cases[{index}].case_id"):
            continue
        if cid in supplied:
            error("inventory.duplicate", cid, "duplicate required case ID")
        supplied[cid] = case
        if cid in core:
            equal(case, core[cid], cid, "inventory.weakened_or_changed_core_case")
        else:
            if case.get("group") not in GROUPS or case.get("mode") not in MODES:
                error("inventory.unsupported_case", cid, "extension case uses unsupported group/mode")
            expected_prefix = f"rr41.{case.get('mode')}.{case.get('group')}."
            if not cid.startswith(expected_prefix):
                error("inventory.case_identity", cid, "ID must include its exact mode and group")
            assertions = array(case.get("assertions"), cid + ".assertions")
            if not assertions or any(not isinstance(a, str) or not a for a in assertions) or len(set(map(str, assertions))) != len(assertions):
                error("inventory.assertions", cid, "nonempty unique assertion IDs are required")
            # Extension requirements must use the verifier's implemented checks.
            req = obj(case.get("requirements"), cid + ".requirements")
            if set(req) - {"meaningful_repetitions", "timing_scenario", "normal_speed_wall_seconds", "scenario_counts", "candidate_postgame_checkpoints"}:
                error("inventory.unknown_requirement", cid, "unsupported acceptance requirement")
    for cid in core.keys() - supplied.keys():
        error("inventory.missing_core_case", cid, "mandatory bundled case cannot be removed")
    cases = dict(core)
    cases.update({cid: c for cid, c in supplied.items()
                  if cid not in core and c.get("mode") in MODES and c.get("group") in GROUPS
                  and isinstance(c.get("requirements"), dict) and isinstance(c.get("assertions"), list)
                  and all(isinstance(a, str) and a for a in c["assertions"])})

    candidate = obj(inv.get("candidate"), "inventory.candidate")
    equal(candidate.get("game"), "rr4.1", "candidate.game")
    equal(candidate.get("base_rom_md5"), BASE_ROM_MD5, "candidate.base_rom_md5")
    equal(candidate.get("native_abi"), 2, "candidate.native_abi")
    for key in ("candidate_id", "native_build_id"):
        nonempty(candidate.get(key), "candidate." + key)
    if not isinstance(candidate.get("source_commit"), str) or not COMMIT.fullmatch(candidate["source_commit"]):
        error("candidate.unresolved", "candidate.source_commit", "pin an exact source commit")
    for key in ("layout_sha256", "capabilities_sha256"):
        if not isinstance(candidate.get(key), str) or not SHA256.fullmatch(candidate[key]):
            error("candidate.unresolved", "candidate." + key, "pin a SHA-256 digest")
    expected_bindings = obj(candidate.get("bindings"), "candidate.bindings")
    expected_fixtures = obj(candidate.get("fixtures"), "candidate.fixtures")
    equal(set(expected_bindings), set(BINDING_ROLES) - {"fixture"}, "candidate.bindings.roles")
    equal(set(expected_fixtures), set(MODES), "candidate.fixtures.modes")
    for key, value in list(expected_bindings.items()) + list(expected_fixtures.items()):
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            error("candidate.unresolved", "candidate.hash." + key, "pin a SHA-256 digest")
    checkpoints = array(candidate.get("postgame_checkpoints"), "candidate.postgame_checkpoints")
    if not checkpoints or any(not isinstance(v, str) or not v.strip() for v in checkpoints) or len(set(map(str, checkpoints))) != len(checkpoints):
        error("candidate.unresolved", "candidate.postgame_checkpoints", "pin nonempty, unique, named supported checkpoints")

    equal(ev.get("schema_version"), 1, "evidence.schema_version")
    nonempty(ev.get("run_id"), "evidence.run_id")
    purpose = ev.get("purpose")
    if purpose not in ("release", "self_test"):
        error("evidence.purpose", "evidence.purpose", "must be release or self_test")
    observed_candidate = obj(ev.get("candidate"), "evidence.candidate")
    for key in ("candidate_id", "source_commit", "game", "base_rom_md5", "native_abi", "native_build_id", "layout_sha256", "capabilities_sha256"):
        equal(observed_candidate.get(key), candidate.get(key), "evidence.candidate." + key)

    root = Path(evidence_root).resolve()
    artifacts = obj(ev.get("artifacts"), "evidence.artifacts")
    checked_artifacts = {}
    for aid, raw in artifacts.items():
        loc = "artifacts." + str(aid)
        art = obj(raw, loc)
        path, digest = art.get("path"), art.get("sha256")
        if not nonempty(path, loc + ".path"):
            continue
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            error("artifact.digest", loc, "expected lowercase SHA-256")
            continue
        # Reject Windows drives/UNC even when tests run on a POSIX host.
        if Path(path).is_absolute() or PureWindowsPath(path).drive or "\\" in path:
            error("artifact.path_escape", loc, "use a relative forward-slash path inside evidence root")
            continue
        try:
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                error("artifact.path_or_missing", loc, "artifact must resolve to a contained regular file")
                continue
        except (OSError, RuntimeError, ValueError) as exc:
            error("artifact.path_or_missing", loc, str(exc))
            continue
        try:
            actual = sha256_file(resolved)
        except OSError as exc:
            error("artifact.read", loc, str(exc))
            continue
        if actual != digest:
            error("artifact.hash_drift", loc, f"declared {digest}; actual {actual}")
            continue
        checked_artifacts[aid] = (art, resolved)

    def artifact_refs(value, loc):
        refs = array(value, loc)
        if not refs:
            error("assertion.no_artifact", loc, "at least one verified artifact is required")
        for aid in refs:
            if not isinstance(aid, str) or aid not in checked_artifacts:
                error("artifact.unverified_reference", loc, f"unverified artifact {aid!r}")

    def bindings(value, mode, loc):
        bound = obj(value, loc)
        equal(set(bound), set(BINDING_ROLES), loc + ".roles")
        for role in BINDING_ROLES:
            aid = bound.get(role)
            if not isinstance(aid, str) or aid not in checked_artifacts:
                error("binding.missing_artifact", loc + "." + role, "verified artifact required")
                continue
            art, _ = checked_artifacts[aid]
            expected = expected_fixtures.get(mode) if role == "fixture" else expected_bindings.get(role)
            equal(art.get("sha256"), expected, loc + "." + role)
            equal(art.get("kind"), role, loc + "." + role + ".kind")
        return bound

    contexts = obj(ev.get("contexts"), "evidence.contexts")
    equal(set(contexts), set(MODES), "evidence.contexts.modes")
    context_bindings = {}
    descriptor_expected = {"game": "rr4.1", "abi": candidate.get("native_abi"),
                           "build_id": candidate.get("native_build_id"),
                           "layout_sha256": candidate.get("layout_sha256"),
                           "capabilities_sha256": candidate.get("capabilities_sha256")}
    for mode in MODES:
        context = obj(contexts.get(mode), "contexts." + mode)
        bound = bindings(context.get("bindings"), mode, "contexts." + mode + ".bindings")
        context_bindings[mode] = bound
        players = array(context.get("players"), "contexts." + mode + ".players")
        equal(sorted(str(p.get("player")) for p in players if isinstance(p, dict)), ["a", "b"], mode + ".players")
        for index, raw in enumerate(players):
            player = obj(raw, f"{mode}.players[{index}]")
            for key, value in (("mode", mode), ("rom", bound.get("rom")), ("patch", bound.get("patch")), ("companion_present", True)):
                equal(player.get(key), value, f"{mode}.player.{key}")
            aid = player.get("native_descriptor")
            if not isinstance(aid, str) or aid not in checked_artifacts:
                error("native.descriptor_missing", mode, "each player requires its captured native descriptor artifact")
                continue
            art, path = checked_artifacts[aid]
            equal(art.get("kind"), "native_descriptor", mode + ".descriptor.kind")
            try:
                if path.stat().st_size > 65536:
                    raise ValueError("native descriptor exceeds 64 KiB")
                descriptor_bytes = path.read_bytes()
                if hashlib.sha256(descriptor_bytes).hexdigest() != art["sha256"]:
                    raise ValueError("descriptor changed after artifact verification")
                descriptor = strict_json(descriptor_bytes.decode("utf-8"))
                equal(descriptor, descriptor_expected, mode + ".descriptor")
            except (OSError, ValueError, UnicodeError) as exc:
                error("native.descriptor_invalid", mode, str(exc))

    records = array(ev.get("records"), "evidence.records")
    record_map = {}
    duplicates = set()
    unexpected = []
    for index, raw in enumerate(records):
        record = obj(raw, f"evidence.records[{index}]")
        cid = record.get("case_id")
        if not nonempty(cid, f"evidence.records[{index}].case_id"):
            continue
        if cid in record_map:
            duplicates.add(cid)
            error("evidence.duplicate_case", cid, "one record per exact case ID; retries cannot replace evidence")
        else:
            record_map[cid] = record
        if cid not in cases:
            unexpected.append(cid)
            error("evidence.unexpected_case", cid, "case not declared in inventory")

    accounting = obj(ev.get("accounting"), "evidence.accounting")
    equal(accounting.get("retry_policy"), "none", "accounting.retry_policy")
    equal(accounting.get("omitted_attempts"), 0, "accounting.omitted_attempts")
    equal(accounting.get("record_count"), len(records), "accounting.record_count")
    for key in ("skipped_case_ids", "xfail_case_ids", "deselected_case_ids"):
        equal(accounting.get(key), [], "accounting." + key)
    selected = array(accounting.get("selected_case_ids"), "accounting.selected_case_ids")
    equal(Counter(map(str, selected)), Counter(cases.keys()), "accounting.selected_case_ids")
    executed = array(accounting.get("executed_case_ids"), "accounting.executed_case_ids")
    equal(Counter(map(str, executed)), Counter(str(r.get("case_id")) for r in records if isinstance(r, dict)), "accounting.executed_case_ids")

    def assertions(value, expected, loc):
        rows = array(value, loc)
        actual = []
        for index, raw in enumerate(rows):
            assertion = obj(raw, f"{loc}[{index}]")
            actual.append(str(assertion.get("id")))
            equal(assertion.get("status"), "pass", loc + ".status", "assertion.not_pass")
            artifact_refs(assertion.get("artifact_ids"), loc + ".artifact_ids")
        equal(Counter(actual), Counter(expected), loc + ".ids", "assertion.missing_duplicate_or_unknown")

    case_results = []
    for cid, case in cases.items():
        before = len(errors)
        record = record_map.get(cid)
        if record is None:
            error("evidence.missing_case", cid, "required case has no evidence")
            case_results.append({"case_id": cid, "mode": case["mode"], "group": case["group"], "state": "missing"})
            continue
        if cid in duplicates:
            error("evidence.duplicate_case", cid, "duplicate records invalidate this case")
        for key, expected in (("mode", case["mode"]), ("run_id", ev.get("run_id")), ("status", "pass"),
                              ("attempt", 1), ("capture_kind", "live" if purpose == "release" else "synthetic")):
            equal(record.get(key), expected, cid + "." + key)
        bound = bindings(record.get("bindings"), case["mode"], cid + ".bindings")
        equal(bound, context_bindings.get(case["mode"]), cid + ".context_bindings")
        assertions(record.get("assertions"), case["assertions"], cid + ".assertions")
        req = case.get("requirements", {})
        if "meaningful_repetitions" in req:
            reps = array(record.get("repetitions"), cid + ".repetitions")
            minimum = req["meaningful_repetitions"]
            if not is_int(minimum, 20):
                error("inventory.repetition_requirement", cid, "minimum meaningful repetitions must be >=20")
                minimum = 20
            equal(record.get("attempt_count"), len(reps), cid + ".attempt_count")
            if len(reps) < minimum:
                error("timing.insufficient_repetitions", cid, f"need at least {minimum} recorded repetitions")
            rep_ids, schedules = [], []
            for index, raw in enumerate(reps):
                rep = obj(raw, f"{cid}.repetitions[{index}]")
                rep_ids.append(str(rep.get("repetition_id")))
                if not nonempty(rep.get("repetition_id"), cid + ".repetition_id"):
                    continue
                equal(rep.get("status"), "pass", cid + ".repetition.status")
                equal(rep.get("attempt"), 1, cid + ".repetition.attempt")
                if not nonempty(req.get("timing_scenario"), cid + ".requirements.timing_scenario"):
                    error("inventory.timing_scenario", cid, "timing repetitions require a named scenario")
                equal(rep.get("scenario"), req.get("timing_scenario"), cid + ".repetition.scenario")
                schedule = obj(rep.get("schedule"), cid + ".repetition.schedule")
                equal(set(schedule), SCHEDULE_FIELDS, cid + ".schedule.fields")
                offset = schedule.get("dispatch_offset_frames")
                if type(offset) is not int or not -120 <= offset <= 120:
                    error("timing.invalid_schedule", cid, "dispatch offset must be an integer between -120 and 120")
                for key in ("latency_ms", "pause_frames"):
                    if not is_int(schedule.get(key)):
                        error("timing.invalid_schedule", cid, f"{key} must be a nonnegative integer")
                if (not isinstance(schedule.get("disconnect_at"), str)
                        or schedule["disconnect_at"] not in DISCONNECT_PHASES
                        or not isinstance(schedule.get("input_pattern"), str)
                        or schedule["input_pattern"] not in INPUT_PATTERNS):
                    error("timing.invalid_schedule", cid, "unknown disconnect/input schedule")
                schedules.append(json.dumps(schedule, sort_keys=True, separators=(",", ":")))
                assertions(rep.get("assertions"), case["assertions"], cid + ".repetition.assertions")
            if len(set(rep_ids)) != len(rep_ids):
                error("timing.duplicate_repetition", cid, "repetition IDs must be unique")
            if len(set(schedules)) < minimum:
                error("timing.insufficient_distinct_schedules", cid, "different IDs/nonces do not make identical schedules meaningful repetitions")
        if "normal_speed_wall_seconds" in req:
            observations = obj(record.get("observations"), cid + ".observations")
            minimum = req["normal_speed_wall_seconds"]
            if not is_int(minimum, 7200):
                error("inventory.soak_requirement", cid, "normal-speed minimum must be >=7200 seconds")
                minimum = 7200
            seconds = observations.get("normal_speed_wall_seconds")
            active = observations.get("active_wall_seconds")
            if type(seconds) not in (int, float) or seconds < minimum:
                error("soak.insufficient_normal_speed", cid, f"need {minimum} normal-speed wall-clock seconds")
            if type(active) not in (int, float) or type(seconds) not in (int, float) or active < seconds:
                error("soak.active_duration", cid, "active duration must cover normal-speed duration")
            equal(observations.get("speed_multiplier_min"), 1.0, cid + ".speed_multiplier_min")
            equal(observations.get("speed_multiplier_max"), 1.0, cid + ".speed_multiplier_max")
            try:
                start = datetime.fromisoformat(observations["started_utc"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(observations["ended_utc"].replace("Z", "+00:00"))
                if start.utcoffset() is None or end.utcoffset() is None:
                    raise ValueError("timestamps require explicit UTC offset")
                elapsed = (end - start).total_seconds()
                if type(active) not in (int, float) or elapsed < active or elapsed <= 0:
                    raise ValueError("recorded interval does not cover active duration")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                error("soak.interval", cid, str(exc))
            counts = obj(observations.get("scenario_counts"), cid + ".scenario_counts")
            for scenario, count in obj(req.get("scenario_counts"), cid + ".requirements.scenario_counts").items():
                if not is_int(count, 1) or not is_int(counts.get(scenario)) or counts[scenario] < count:
                    error("soak.scenario_count", cid + "." + scenario, f"need at least {count} completed scenarios")
        if req.get("candidate_postgame_checkpoints"):
            observations = obj(record.get("observations"), cid + ".observations")
            completed = array(observations.get("completed_checkpoints"), cid + ".completed_checkpoints")
            equal(Counter(map(str, completed)), Counter(map(str, checkpoints)), cid + ".completed_checkpoints")
        case_results.append({"case_id": cid, "mode": case["mode"], "group": case["group"],
                             "state": "passed" if len(errors) == before else "failed"})

    states = Counter(row["state"] for row in case_results)
    coverage = []
    for mode in MODES:
        for group in GROUPS:
            counts = Counter(row["state"] for row in case_results if row["mode"] == mode and row["group"] == group)
            coverage.append({"mode": mode, "group": group, "required": sum(counts.values()),
                             **{state: counts[state] for state in ("passed", "failed", "missing")}})
    verification_passed = not errors
    release_ready = verification_passed and purpose == "release"
    return {"schema_version": 1, "inventory_id": inv.get("inventory_id"), "run_id": ev.get("run_id"),
            "purpose": purpose, "verification_passed": verification_passed, "release_ready": release_ready,
            "verdict": "PASS" if release_ready else ("SELF_TEST_ONLY" if verification_passed else "FAIL"),
            "provenance_limit": "Checks completeness, declared contract, and artifact content hashes; cannot authenticate capture truth or prove gameplay from arbitrary bytes.",
            "summary": {"required": len(cases), "records": len(records), "provided_unique": len(set(record_map) & set(cases)),
                        **{state: states[state] for state in ("passed", "failed", "missing")},
                        "unexpected": len(unexpected), "duplicates": len(duplicates), "errors": len(errors)},
            "coverage": coverage, "errors": errors, "case_results": case_results}


def human_report(report):
    s = report["summary"]
    lines = [f"RR release gate: {report['verdict']}",
             f"Required {s['required']}; passed {s['passed']}; failed {s['failed']}; missing {s['missing']}; unexpected {s['unexpected']}; duplicates {s['duplicates']}."]
    for mode in MODES:
        rows = [r for r in report["coverage"] if r["mode"] == mode]
        lines.append(f"{mode}: {sum(r['passed'] for r in rows)}/{sum(r['required'] for r in rows)} required cases passed.")
    if report["purpose"] == "self_test":
        lines.append("Synthetic self-test only. This is not release evidence.")
    for item in report["errors"][:6]:
        lines.append(f"- {item['code']}: {item['location']}: {item['message']}")
    if len(report["errors"]) > 6:
        lines.append(f"- {len(report['errors']) - 6} further errors in JSON report.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", nargs="?", const="-", help="candidate inventory JSON; omit value to print the bundled uncompleted inventory")
    parser.add_argument("--evidence", help="captured evidence JSON; its parent is the artifact root")
    parser.add_argument("--output", help="write JSON report (or printed inventory) here")
    args = parser.parse_args(argv)
    if args.inventory == "-" and not args.evidence:
        inventory = build_inventory()
        content = json.dumps(inventory, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(content, encoding="utf-8")
        else:
            print(content, end="")
        print(f"Inventory only: {len(inventory['cases'])} required cases; no completed evidence; candidate bindings unresolved.", file=sys.stderr)
        return 0
    if not args.evidence:
        parser.error("--evidence is required for verification (use --inventory alone to inspect requirements)")
    evidence_path = Path(args.evidence)
    input_paths = [evidence_path.resolve()]
    if args.inventory not in (None, "-"):
        input_paths.append(Path(args.inventory).resolve())
    if args.output and Path(args.output).resolve() in input_paths:
        parser.error("--output must not overwrite an input inventory or evidence file")
    load_errors = []
    def load(path, label):
        try:
            return strict_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            load_errors.append({"code": "input.invalid", "location": label, "message": str(exc)})
            return {}
    inventory = build_inventory() if args.inventory in (None, "-") else load(args.inventory, "inventory")
    evidence = load(evidence_path, "evidence")
    if args.output:
        output_path = Path(args.output).resolve()
        protected = list(input_paths)
        if isinstance(evidence, dict) and isinstance(evidence.get("artifacts"), dict):
            for art in evidence["artifacts"].values():
                if isinstance(art, dict) and isinstance(art.get("path"), str):
                    with suppress(OSError, RuntimeError, ValueError):
                        protected.append((evidence_path.parent / art["path"]).resolve())
        for source_path in protected:
            same_file = output_path == source_path
            if not same_file and output_path.exists() and source_path.exists():
                same_file = output_path.samefile(source_path)
            if same_file:
                parser.error("--output must not overwrite input JSON or any referenced artifact (including aliases)")
    report = verify(inventory, evidence, evidence_path.parent)
    if load_errors:
        report["errors"] = load_errors + report["errors"]
        report["summary"]["errors"] = len(report["errors"])
        report.update(verification_passed=False, release_ready=False, verdict="FAIL")
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        print(human_report(report))
    else:
        print(content, end="")
        print(human_report(report), file=sys.stderr)
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
