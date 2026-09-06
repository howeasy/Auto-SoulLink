#!/usr/bin/env python3
"""Fail-closed RBY release gate with machine-readable evidence.

--quick runs fast diagnostics and can NEVER produce a release pass.
--list lists all ten stages and their concrete missing proof IDs.
--write-inventory explicitly refreshes collection only, without executing tests.
Review the inventory diff; collection does not establish requirement coverage.
After a green automated run, --complete-human <automation.json> plus
--human-attestation <session.json> verifies the staged two-player human session.

Generated reports stay beneath this worktree's .cache/gen1-release/. A registered
proof names reviewed assertions and their source hash; test names/counts alone do
not establish gameplay coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tests/gen1_release_requirements.json"
INVENTORY = REPO / "tests/gen1_release_inventory.json"
INPUTS = REPO / "tests/gen1_release_inputs.json"
REPORT_ROOT = REPO / ".cache/gen1-release"
STAGES = ("canonical-validation", "unit-protocol", "live-memory", "single-player",
          "live-duos", "ordered-contracts", "manager-isolation", "patch-browser",
          "trade-receptionist", "human-session")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def proof_sha256(path: Path) -> str:
    """Review pins normalize source line endings; artifact and runtime pins stay raw.

Git's text checkout rules can change CRLF/LF without changing an assertion. Binary
payloads, fixture saves, canonical artifacts and before/after snapshots are never
normalized by their integrity checks.
    """
    if path.suffix in {".py", ".lua", ".asm", ".json"}:
        return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return sha256(path)


def local_path(value: str, root: Path = REPO) -> Path:
    """Manifest/report references may never escape the selected worktree."""
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path leaves worktree: {value}")
    return path


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError(f"unsupported evidence schema: {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_pytest_report(report: dict, expected: list[str], token: str,
                           collect_only: bool = False) -> list[str]:
    """Require passed setup, call AND teardown exactly once per expected test."""
    problems = []
    if report.get("schema") != 1 or report.get("token") != token:
        problems.append("missing, stale or unsupported pytest evidence")
    if report.get("exitstatus") != 0:
        problems.append(f"pytest exit status {report.get('exitstatus')}")
    collected = report.get("collected", [])
    if (not isinstance(collected, list) or not collected
            or any(not isinstance(item, str) for item in collected)):
        return problems + ["pytest collected no valid test inventory"]
    if len(set(collected)) != len(collected):
        problems.append("duplicate collected test IDs")
    if report.get("collected_count") != len(collected):
        problems.append("pytest collected-count mismatch")
    if not collect_only and Counter(collected) != Counter(expected):
        missing = sorted(set(expected) - set(collected))
        added = sorted(set(collected) - set(expected))
        problems.append(f"test inventory drift: missing={missing}, unreviewed={added}")
    for field in ("deselected", "collection_problems", "internal_errors"):
        if report.get(field) != []:
            problems.append(f"pytest {field}: {report.get(field)}")
    if collect_only:
        return problems
    phases = defaultdict(list)
    for result in report.get("reports", []):
        if not isinstance(result, dict):
            problems.append("malformed pytest phase report")
            continue
        nodeid = result.get("nodeid")
        phases[nodeid].append(result.get("when"))
        if result.get("outcome") != "passed" or result.get("wasxfail") is not False:
            problems.append(f"{nodeid} {result.get('when')}: "
                            f"{result.get('outcome')} wasxfail={result.get('wasxfail')}")
    if set(phases) != set(collected):
        problems.append("missing or unexpected test execution reports")
    for nodeid, seen in phases.items():
        if Counter(seen) != Counter(("setup", "call", "teardown")):
            problems.append(f"{nodeid}: incomplete or repeated execution phases {seen}")
    return problems


def diagnostic_problems(output: str) -> list[str]:
    """Validators may not hide warnings/skips behind a successful exit code."""
    return [line.strip() for line in output.splitlines() if re.search(
        r"(?i)^\s*\[(?:WARN(?:ING)?|SKIP)\]|^\s*(?:WARN(?:ING)?|SKIP)\b"
        r"|\b[1-9][0-9]*\s+(?:WARN(?:ING)?S?|SKIPS?)\b"
        r'|"(?:severity|status|outcome)"\s*:\s*"(?:warn(?:ing)?|skip(?:ped)?)"', line)]


def verified_passes(report: dict, expected: list[str], token: str) -> list[str]:
    """Preserve honest per-test coverage when an unrelated test fails the whole lane."""
    structural = dict(report, exitstatus=0)
    if validate_pytest_report(structural, expected, token, collect_only=True):
        return []
    if Counter(report["collected"]) != Counter(expected):
        return []
    passed = []
    for nodeid in report["collected"]:
        individual = dict(structural, collected=[nodeid], collected_count=1,
                          reports=[r for r in report["reports"] if r.get("nodeid") == nodeid])
        if not validate_pytest_report(individual, [nodeid], token):
            passed.append(nodeid)
    return passed


def snapshot_inputs(manifest: dict, root: Path = REPO) -> dict[str, str]:
    paths = set()
    for pattern in manifest["protected_globs"]:
        paths.update(path for path in root.glob(pattern) if path.is_file())
    return {path.relative_to(root).as_posix(): sha256(path) for path in sorted(paths)}


def compare_snapshots(before: dict, after: dict) -> list[str]:
    return [f"immutable input changed: {name}" for name in sorted(set(before) | set(after))
            if before.get(name) != after.get(name)]


def prerequisite_problems(manifest: dict, pinned: dict, root: Path = REPO) -> list[str]:
    problems = []
    for name, digest in pinned["files"].items():
        path = local_path(name, root)
        if not path.is_file():
            problems.append(f"missing pinned input: {name}")
        elif not re.fullmatch(r"[0-9a-f]{64}", str(digest)) or sha256(path) != digest:
            problems.append(f"pinned input hash drift: {name}")
    for entry in manifest["prerequisites"]:
        configured = os.environ.get(entry.get("env", ""))
        value = configured or entry.get("path")
        if not value:
            problems.append(f"missing prerequisite: {entry['id']} ({entry.get('env')})")
            continue
        # Dependencies may live outside the worktree; outputs may not.
        path = Path(value) if configured or entry.get("external") else local_path(value, root)
        if entry.get("executable"):
            found = shutil.which(str(value))
            path = Path(found) if found else path
        if not path.is_file():
            problems.append(f"missing prerequisite: {entry['id']} ({path})")
            continue
        expected = entry.get("hash")
        if entry.get("require_pin") and not expected:
            problems.append(f"unreviewed prerequisite hash: {entry['id']}")
        if entry.get("hash_algorithm") and expected:
            actual = hashlib.new(entry["hash_algorithm"], path.read_bytes()).hexdigest()
            if actual != expected:
                problems.append(f"prerequisite hash drift: {entry['id']}")
        # Also identify the actual core/Lua/API assemblies beside this executable.
        for relative, digest in entry.get("adjacent_files_sha256", {}).items():
            label = f"{entry['id']}/{relative}"
            try:
                adjacent = local_path(relative, path.parent)
            except ValueError:
                problems.append(f"prerequisite file leaves runtime directory: {label}")
                continue
            if not adjacent.is_file():
                problems.append(f"missing prerequisite: {label}")
            elif not re.fullmatch(r"[0-9a-f]{64}", str(digest)) or sha256(adjacent) != digest:
                problems.append(f"prerequisite hash drift: {label}")
    return problems


def run_check(check: dict, output_dir: Path, expected: list[str] | None,
              collect_only: bool = False, root: Path = REPO) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = output_dir / f"{check['id']}-tmp"
    temporary_dir.mkdir()
    token = secrets.token_hex(16)
    evidence = output_dir / f"{check['id']}.pytest.json"
    argv = [sys.executable if value == "{python}" else value for value in check["argv"]]
    if check["kind"] == "pytest":
        argv += ["-p", "tools.gen1_release_pytest", "--gen1-release-report", str(evidence),
                 "--gen1-release-token", token, "--basetemp", str(temporary_dir / "pytest")]
        if collect_only:
            argv.append("--collect-only")
    env = dict(os.environ)
    env.update(check.get("env", {}))
    env.update(TMP=str(temporary_dir), TEMP=str(temporary_dir), TMPDIR=str(temporary_dir))
    started = time.monotonic()
    problems = []
    result = {"id": check["id"], "kind": check["kind"], "argv": argv,
              "status": "failed", "problems": problems}
    try:
        process = subprocess.run(argv, cwd=root, env=env, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 timeout=check.get("timeout_seconds", 3600))
        output = (process.stdout or "") + (process.stderr or "")
        result["exitstatus"] = process.returncode
        if process.returncode != 0:
            problems.append(f"process exit status {process.returncode}")
        if check.get("strict_diagnostics"):
            problems.extend(diagnostic_problems(output))
        if check["kind"] == "pytest":
            try:
                report = read_json(evidence)
                problems.extend(validate_pytest_report(report, expected or [], token, collect_only))
                result["collected"] = report.get("collected", [])
                result["verified_passes"] = ([] if collect_only else
                    verified_passes(report, expected or [], token))
                result["evidence"] = evidence.relative_to(root).as_posix()
                result["evidence_sha256"] = sha256(evidence)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                problems.append(f"pytest evidence unavailable: {exc}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        output = str(exc)
        problems.append(f"check did not complete: {exc}")
    output_dir.mkdir(parents=True, exist_ok=True)
    log = output_dir / f"{check['id']}.log"
    log.write_text(output, encoding="utf-8")
    result["log"] = log.relative_to(root).as_posix()
    result["log_sha256"] = sha256(log)
    result["seconds"] = round(time.monotonic() - started, 3)
    if not problems:
        result["status"] = "passed"
    return result


def evaluate_requirements(manifest: dict, checks: dict, root: Path = REPO) -> list[dict]:
    """Only registered, reviewed assertion implementations can provide proof."""
    rows = []
    for requirement in manifest["requirements"]:
        errors = []
        if not requirement["proofs"]:
            errors.append("no reviewed executable proof registered")
        for proof in requirement["proofs"]:
            check = checks.get(proof.get("check"))
            test_passed = (check and check.get("kind") == "pytest"
                           and proof.get("nodeid") in check.get("verified_passes", []))
            if not check or (check.get("status") != "passed" and not test_passed):
                errors.append(f"required check did not pass: {proof.get('check')}")
            if not proof.get("assertion_basis", "").strip():
                errors.append("missing explanation of authoritative assertions")
            try:
                source = local_path(proof["source"], root)
                if proof_sha256(source) != proof.get("source_sha256"):
                    errors.append(f"reviewed proof implementation drift: {proof['source']}")
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"proof implementation unavailable: {exc}")
            for name, digest in proof.get("supporting_sources", {}).items():
                try:
                    if proof_sha256(local_path(name, root)) != digest:
                        errors.append(f"reviewed proof dependency drift: {name}")
                except (OSError, ValueError) as exc:
                    errors.append(f"proof dependency unavailable: {exc}")
            if check and check["kind"] == "pytest":
                if not test_passed:
                    errors.append(f"assertion-bearing test did not execute: {proof.get('nodeid')}")
            elif check and check["kind"] != "validator":
                errors.append("unsupported proof kind")
        rows.append({"id": requirement["id"], "stage": requirement["stage"],
                     "description": requirement["description"],
                     "status": "missing" if errors else "passed", "problems": errors})
    return rows


def validate_manifest(manifest: dict) -> None:
    stages = [stage["id"] for stage in manifest["stages"]]
    if tuple(stages) != STAGES:
        raise ValueError("manifest must retain all ten distinct release stages")
    for collection in (manifest["requirements"], manifest["checks"], manifest["prerequisites"]):
        ids = [entry["id"] for entry in collection]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError("manifest contains missing or duplicate IDs")
    for requirement in manifest["requirements"]:
        if requirement["stage"] not in stages or not isinstance(requirement["proofs"], list):
            raise ValueError(f"invalid requirement: {requirement['id']}")
    if {r["stage"] for r in manifest["requirements"]} != set(STAGES):
        raise ValueError("every release stage must retain concrete requirements")
    required_contracts = {f"contract.{a}.{b}.hello-{order}"
                          for a in ("red", "blue", "yellow")
                          for b in ("red", "blue", "yellow") for order in ("ab", "ba")}
    actual = {row["id"] for row in manifest["requirements"] if row["stage"] == "ordered-contracts"}
    if actual != required_contracts:
        raise ValueError("all nine ordered contracts in both HELLO orders are mandatory")


def human_session_problems(attestation: dict | None, automated: dict,
                           root: Path = REPO) -> list[str]:
    if not automated["automation_passed"]:
        return ["human session is gated on complete passing automation"]
    if not attestation:
        return ["staged two-player human session has not been attested"]
    errors = []
    if attestation.get("automation_report_sha256") != automated["automation_report_sha256"]:
        errors.append("human session refers to different automated evidence")
    players = attestation.get("players", [])
    if (not isinstance(players, list) or len(players) != 2 or
            any(not isinstance(p, str) or not p.strip() for p in players) or players[0] == players[1]):
        errors.append("two distinct human participants must attest")
    if not attestation.get("completed_at_utc") or not attestation.get("session_notes"):
        errors.append("human session completion time and notes are required")
    if attestation.get("defects") != []:
        errors.append("human defects require regressions and a fresh passing gate/session")
    try:
        notes = local_path(attestation["session_notes"], root)
        if sha256(notes) != attestation.get("session_notes_sha256"):
            errors.append("human session notes hash mismatch")
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"human session notes unavailable: {exc}")
    return errors


def complete_human(automation_path: Path, attestation_path: Path | None,
                   manifest: dict) -> int:
    report = read_json(automation_path)
    report["automation_report_sha256"] = sha256(automation_path)
    errors = compare_snapshots(report["input_sha256"], snapshot_inputs(manifest))
    errors.extend(prerequisite_problems(manifest, read_json(INPUTS)))
    if report.get("quick") is not False or report.get("input_drift") != []:
        errors.append("diagnostic or mutated-input runs cannot support a human verdict")
    expected_checks = {check["id"] for check in manifest["checks"]}
    if set(report["checks"]) != expected_checks:
        errors.append("automation did not include every required check")
    inventory = read_json(INVENTORY)["checks"]
    for check in report["checks"].values():
        if check.get("status") != "passed":
            errors.append(f"automation check did not pass: {check.get('id')}")
        for field in ("log", "evidence"):
            if field in check:
                path = local_path(check[field])
                if not path.is_file() or sha256(path) != check[field + "_sha256"]:
                    errors.append(f"automated evidence hash drift: {check[field]}")
        if check.get("kind") == "pytest":
            raw = read_json(local_path(check["evidence"]))
            args = check["argv"]
            token = args[args.index("--gen1-release-token") + 1]
            errors.extend(validate_pytest_report(raw, inventory[check["id"]], token))
    current_coverage = evaluate_requirements(manifest, report["checks"])
    if any(row["status"] != "passed" for row in current_coverage
           if row["stage"] != "human-session"):
        errors.append("required automated coverage is incomplete")
    report["requirements"] = current_coverage
    attestation = read_json(attestation_path) if attestation_path else None
    errors.extend(human_session_problems(attestation, report))
    report["human_session_problems"] = errors
    report["release_passed"] = not errors
    if not errors:
        for row in report["requirements"]:
            if row["stage"] == "human-session":
                row.update(status="passed", problems=[])
    final = automation_path.parent / "human-verdict.json"
    write_json(final, report)
    print(f"{'GATE FAILED' if errors else 'GATE PASSED'}: {final}")
    return int(bool(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--write-inventory", action="store_true")
    parser.add_argument("--verify-inputs", action="store_true", help="check pinned fixtures and runtime dependencies without executing tests")
    parser.add_argument("--complete-human", help="worktree-relative passing automation.json")
    parser.add_argument("--human-attestation", help="worktree-relative JSON attestation")
    args = parser.parse_args(argv)
    try:
        manifest = read_json(MANIFEST)
        validate_manifest(manifest)
        if args.complete_human:
            return complete_human(local_path(args.complete_human),
                                  local_path(args.human_attestation) if args.human_attestation else None,
                                  manifest)
        pinned = read_json(INPUTS)
        if args.verify_inputs:
            problems = prerequisite_problems(manifest, pinned)
            if problems:
                for problem in problems:
                    print("FAIL: " + problem)
            else:
                print("OK: required input and runtime hashes match")
            return int(bool(problems))
        inventory = {} if args.write_inventory else read_json(INVENTORY)["checks"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"GATE FAILED: invalid gate inputs: {exc}")
        return 1
    if args.list:
        for stage in manifest["stages"]:
            print(f"{stage['id']}: {stage['description']}")
            for row in manifest["requirements"]:
                if row["stage"] == stage["id"]:
                    print(f"  {row['id']}: {'registered' if row['proofs'] else 'MISSING PROOF'}")
        return 0
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    output_dir = REPORT_ROOT / run_id
    output_dir.mkdir(parents=True)
    before = snapshot_inputs(manifest)
    prerequisites = prerequisite_problems(manifest, pinned)
    results = {}
    for check in manifest["checks"]:
        if args.write_inventory and check["kind"] != "pytest":
            continue
        if args.quick and check.get("slow"):
            continue
        # Keep cheap diagnostics available, but never start emulators without inputs.
        if check.get("slow") and not args.write_inventory and (
                prerequisites or any(r["status"] != "passed" for r in results.values())):
            results[check["id"]] = {"id": check["id"], "kind": check["kind"],
                "status": "blocked", "problems": ["prerequisites or earlier checks failed"]}
            continue
        print(f"[ RUN ] {check['id']}", flush=True)
        result = run_check(check, output_dir, inventory.get(check["id"]), args.write_inventory)
        check_drift = compare_snapshots(before, snapshot_inputs(manifest))
        if check_drift:
            result["problems"].extend(check_drift)
            result["status"] = "failed"
            result["verified_passes"] = []
        results[check["id"]] = result
        print(f"[{result['status'].upper()}] {check['id']} ({result['seconds']:.1f}s)", flush=True)
        if not args.quiet:
            for problem in result["problems"]:
                print(f"  {problem}")
    drift = compare_snapshots(before, snapshot_inputs(manifest))
    if args.write_inventory:
        if args.quick or drift or any(r["status"] != "passed" for r in results.values()):
            print("Inventory refresh failed; no inventory was written.")
            return 1
        write_json(INVENTORY, {"schema": 1, "checks": {
            name: result["collected"] for name, result in results.items()}})
        print("Inventory refreshed. Review its diff; this is not execution evidence.")
        return 0
    # External read-only dependencies (notably the user-supplied UPR JAR) are not in
    # worktree glob snapshots. Recheck their pins after all subprocesses finish.
    prerequisites = list(dict.fromkeys([
        *prerequisites, *prerequisite_problems(manifest, pinned)]))
    coverage = evaluate_requirements(manifest, results)
    automated_coverage = [row for row in coverage if row["stage"] != "human-session"]
    automation_passed = (not args.quick and not prerequisites and not drift
                         and set(results) == {c["id"] for c in manifest["checks"]}
                         and all(r["status"] == "passed" for r in results.values())
                         and all(r["status"] == "passed" for r in automated_coverage))
    report = {"schema": 1, "run_id": run_id, "quick": args.quick,
              "automation_passed": automation_passed, "release_passed": False,
              "prerequisite_problems": prerequisites, "input_drift": drift,
              "input_sha256": before, "checks": results, "requirements": coverage}
    final_path = output_dir / "automation.json"
    write_json(final_path, report)
    missing = sum(row["status"] != "passed" for row in automated_coverage)
    print(f"Report: {final_path}")
    print(f"{len(prerequisites)} prerequisite failures, {len(drift)} input mutations, "
          f"{missing} missing automated requirements.")
    if automation_passed:
        print("AUTOMATION PASSED; release awaits the staged two-player human session.")
    else:
        print("GATE FAILED" + (" (quick diagnostics are never a release verdict)" if args.quick else ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
