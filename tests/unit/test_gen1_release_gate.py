"""Adversarial gate regressions using genuine subprocess pytest phase reports."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from tools import verify_gen1_release as gate


def good_report():
    return {"schema": 1, "token": "this-run", "exitstatus": 0,
            "collected": ["test_one.py::test_ok"], "collected_count": 1,
            "deselected": [], "collection_problems": [], "internal_errors": [],
            "reports": [{"nodeid": "test_one.py::test_ok", "when": phase,
                         "outcome": "passed", "wasxfail": False}
                        for phase in ("setup", "call", "teardown")]}


@pytest.mark.parametrize("change", [
    lambda r: r.update(token="previous-run"),
    lambda r: r.update(reports=[]),
    lambda r: r["reports"].pop(),
    lambda r: r["reports"].append(r["reports"][1]),
    lambda r: r["reports"][1].update(outcome="skipped"),
    lambda r: r["reports"][1].update(wasxfail=True),
    lambda r: r["reports"][2].update(outcome="failed"),
    lambda r: r.update(deselected=["test_one.py::test_hidden"]),
    lambda r: r.update(collection_problems=[{"outcome": "skipped"}]),
    lambda r: r.update(internal_errors=["dispatcher stopped"]),
    lambda r: r.update(collected_count=2),
    lambda r: r.update(exitstatus=1),
])
def test_zero_exit_or_passing_call_cannot_hide_incomplete_execution(change):
    report = good_report()
    change(report)
    assert gate.validate_pytest_report(report, ["test_one.py::test_ok"], "this-run")


def test_expected_test_disappearance_fails_even_when_remaining_tests_pass():
    assert gate.validate_pytest_report(good_report(),
        ["test_one.py::test_ok", "test_one.py::test_required"], "this-run")


def test_complete_current_execution_passes():
    assert gate.validate_pytest_report(good_report(), ["test_one.py::test_ok"], "this-run") == []


@pytest.mark.parametrize("body,args,passes", [
    ("def test_case():\n    assert True\n", [], True),
    ("def test_case():\n    print('999 passed')\n    pytest.skip('allowed skip')\n", [], False),
    ("@pytest.mark.xfail\ndef test_case():\n    assert False\n", [], False),
    ("@pytest.mark.xfail(strict=False)\ndef test_case():\n    assert True\n", [], False),
    ("@pytest.fixture\ndef broken():\n    yield\n    assert False\n"
     "def test_case(broken):\n    assert True\n", [], False),
    ("pytest.skip('collection skip', allow_module_level=True)\n", [], False),
    ("def test_case():\n    assert True\ndef test_omitted():\n    assert True\n",
     ["-k", "test_case"], False),
])
def test_actual_pytest_reports_reject_nonpassing_outcomes(tmp_path, body, args, passes):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_probe.py").write_text("import pytest\n" + body, encoding="utf-8")
    output = tmp_path / "evidence.json"
    env = dict(os.environ, PYTHONPATH=str(gate.REPO), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    process = subprocess.run([sys.executable, "-m", "pytest", "test_probe.py", "-q",
        "-p", "tools.gen1_release_pytest", "--gen1-release-report", str(output),
        "--gen1-release-token", "this-run", *args], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30)
    assert output.is_file(), process.stdout + process.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    problems = gate.validate_pytest_report(report, ["test_probe.py::test_case"], "this-run")
    assert (not problems) == passes, problems


@pytest.mark.parametrize("text", ["[WARN] address unmapped", "  [SKIP] offset",
                                      "Summary: 213 OK / 122 SKIP", "WARNING: field",
                                      '{"severity": "WARN"}', '{"outcome":"skipped"}'])
def test_zero_exit_validator_warning_is_failure(text):
    assert gate.diagnostic_problems(text)


def test_clean_validator_diagnostics_are_not_false_positives():
    assert gate.diagnostic_problems("Summary: 466 OK / 0 FAIL / 0 WARN / 0 SKIP") == []


def test_fixture_mutation_deletion_and_addition_fail(tmp_path):
    (tmp_path / "fixtures").mkdir()
    fixture = tmp_path / "fixtures/red.SaveRAM"
    fixture.write_bytes(b"original")
    manifest = {"protected_globs": ["fixtures/*"]}
    before = gate.snapshot_inputs(manifest, tmp_path)
    fixture.write_bytes(b"changed")
    assert gate.compare_snapshots(before, gate.snapshot_inputs(manifest, tmp_path))
    fixture.unlink()
    assert gate.compare_snapshots(before, gate.snapshot_inputs(manifest, tmp_path))
    fixture.write_bytes(b"original")
    (fixture.parent / "blue.SaveRAM").write_bytes(b"new")
    assert gate.compare_snapshots(before, gate.snapshot_inputs(manifest, tmp_path))


def test_required_input_missing_or_drifted_fails_before_emulation(tmp_path):
    fixture = tmp_path / "red.SaveRAM"
    fixture.write_bytes(b"canonical")
    pins = {"files": {"red.SaveRAM": gate.sha256(fixture)}}
    manifest = {"prerequisites": []}
    assert gate.prerequisite_problems(manifest, pins, tmp_path) == []
    fixture.write_bytes(b"mutated")
    assert "hash drift" in gate.prerequisite_problems(manifest, pins, tmp_path)[0]
    fixture.unlink()
    assert "missing pinned" in gate.prerequisite_problems(manifest, pins, tmp_path)[0]


def test_review_pins_are_portable_but_artifact_integrity_remains_byte_exact(tmp_path):
    source = tmp_path / "proof.py"
    source.write_bytes(b"assert expected == actual\n")
    original = gate.proof_sha256(source)
    raw = gate.sha256(source)
    source.write_bytes(b"assert expected == actual\r\n")
    assert gate.proof_sha256(source) == original
    assert gate.sha256(source) != raw
    binary = tmp_path / "payload.bin"
    binary.write_bytes(b"\r\n")
    assert gate.proof_sha256(binary) == gate.sha256(binary)


def test_existing_unpinned_randomizer_is_not_accepted(tmp_path, monkeypatch):
    jar = tmp_path / "PokeRandoZX.jar"
    jar.write_bytes(b"not proof of official distribution")
    monkeypatch.setenv("SLINK_UPR_JAR", str(jar))
    manifest = {"prerequisites": [{"id": "upr", "env": "SLINK_UPR_JAR",
                                   "require_pin": True}]}
    assert gate.prerequisite_problems(manifest, {"files": {}}, tmp_path) == [
        "unreviewed prerequisite hash: upr"]


def test_pinned_external_source_is_read_only_and_hash_checked(tmp_path):
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    package = tmp_path / "installed.apworld"
    package.write_bytes(b"installed user dependency")
    manifest = {"prerequisites": [{"id": "ap-source", "path": str(package), "external": True,
        "require_pin": True, "hash_algorithm": "sha256", "hash": gate.sha256(package)}]}
    assert gate.prerequisite_problems(manifest, {"files": {}}, workspace) == []
    assert package.read_bytes() == b"installed user dependency"
    package.write_bytes(b"changed package")
    assert gate.prerequisite_problems(manifest, {"files": {}}, workspace) == [
        "prerequisite hash drift: ap-source"]


def test_runtime_core_drift_is_rejected_even_when_executable_is_unchanged(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    exe, core = runtime / "EmuHawk.exe", runtime / "core.dll"
    exe.write_bytes(b"same executable")
    core.write_bytes(b"reviewed core")
    monkeypatch.setenv("SLINK_EMUHAWK", str(exe))
    entry = {"id": "emulator", "env": "SLINK_EMUHAWK", "hash_algorithm": "sha256",
             "hash": gate.sha256(exe), "adjacent_files_sha256": {"core.dll": gate.sha256(core)}}
    manifest = {"prerequisites": [entry]}
    assert gate.prerequisite_problems(manifest, {"files": {}}, tmp_path) == []
    core.write_bytes(b"changed core")
    assert gate.prerequisite_problems(manifest, {"files": {}}, tmp_path) == [
        "prerequisite hash drift: emulator/core.dll"]
    second = tmp_path / "other-runtime"
    second.mkdir()
    (second / "EmuHawk.exe").write_bytes(exe.read_bytes())
    monkeypatch.setenv("SLINK_EMUHAWK", str(second / "EmuHawk.exe"))
    assert gate.prerequisite_problems(manifest, {"files": {}}, tmp_path) == [
        "missing prerequisite: emulator/core.dll"]
    entry["adjacent_files_sha256"] = {"../runtime/core.dll": gate.sha256(core)}
    assert "leaves runtime directory" in gate.prerequisite_problems(manifest, {"files": {}}, tmp_path)[0]


def test_test_names_do_not_satisfy_missing_requirement_proofs():
    manifest = {"requirements": [{"id": "trade.full-fidelity", "stage": "trade",
                 "description": "All authoritative bytes preserved", "proofs": []}]}
    checks = {"unit": {"kind": "pytest", "status": "passed",
                        "collected": ["test_trade.py::test_full_fidelity"]}}
    assert gate.evaluate_requirements(manifest, checks)[0]["status"] == "missing"


def test_reviewed_assertion_must_execute_and_keep_its_source_hash(tmp_path):
    source = tmp_path / "test_trade.py"
    source.write_text("assert received == expected\n", encoding="utf-8")
    proof = {"check": "unit", "nodeid": "test_trade.py::test_trade", "source": source.name,
             "source_sha256": gate.proof_sha256(source), "assertion_basis": "Compares all 66 bytes"}
    manifest = {"requirements": [{"id": "trade.fidelity", "stage": "trade",
                 "description": "66-byte fidelity", "proofs": [proof]}]}
    checks = {"unit": {"kind": "pytest", "status": "passed",
                       "collected": [proof["nodeid"]], "verified_passes": [proof["nodeid"]]}}
    assert gate.evaluate_requirements(manifest, checks, tmp_path)[0]["status"] == "passed"
    source.write_text("assert True\n", encoding="utf-8")
    assert gate.evaluate_requirements(manifest, checks, tmp_path)[0]["status"] == "missing"


def test_partial_coverage_requires_actual_passed_phases_and_complete_collection():
    report = good_report()
    other = "test_one.py::test_bad"
    report.update(exitstatus=1, collected_count=2)
    report["collected"].append(other)
    report["reports"].extend({"nodeid": other, "when": phase, "wasxfail": False,
        "outcome": "failed" if phase == "call" else "passed"}
        for phase in ("setup", "call", "teardown"))
    assert gate.verified_passes(report, report["collected"], "this-run") == ["test_one.py::test_ok"]
    assert gate.validate_pytest_report(report, report["collected"], "this-run")
    assert gate.verified_passes(report, report["collected"], "stale-run") == []
    assert gate.verified_passes(report, [*report["collected"], "missing"], "this-run") == []


def test_nine_ordered_pairs_in_both_hello_orders_cannot_be_omitted():
    manifest = gate.read_json(gate.MANIFEST)
    gate.validate_manifest(manifest)
    modified = copy.deepcopy(manifest)
    modified["requirements"] = [r for r in modified["requirements"]
                                if r["id"] != "contract.yellow.blue.hello-ba"]
    with pytest.raises(ValueError, match="nine ordered"):
        gate.validate_manifest(modified)


def test_manifest_paths_cannot_leave_worktree(tmp_path):
    with pytest.raises(ValueError, match="leaves worktree"):
        gate.local_path("../original-checkout/fixture", tmp_path)


def test_human_cannot_override_failed_automation():
    assert gate.human_session_problems({"approved": True}, {"automation_passed": False})


def test_human_attestation_is_bound_to_automation_and_notes(tmp_path):
    notes = tmp_path / "session.md"
    notes.write_text("Two humans exercised the staged flow.\n", encoding="utf-8")
    automated = {"automation_passed": True, "automation_report_sha256": "a" * 64}
    attestation = {"automation_report_sha256": "a" * 64, "players": ["A", "B"],
                   "completed_at_utc": "2026-09-04T00:00:00Z", "session_notes": notes.name,
                   "session_notes_sha256": gate.sha256(notes), "defects": []}
    assert gate.human_session_problems(attestation, automated, tmp_path) == []
    attestation["automation_report_sha256"] = "b" * 64
    assert gate.human_session_problems(attestation, automated, tmp_path)
    attestation["automation_report_sha256"] = "a" * 64
    attestation["defects"] = ["uncovered save loss"]
    assert gate.human_session_problems(attestation, automated, tmp_path)


@pytest.mark.parametrize("mode", ["quick", "missing-prerequisite", "fixture-mutation"])
def test_cli_never_promotes_incomplete_automation_or_launches_blocked_emulators(
        tmp_path, monkeypatch, mode):
    """Exercise the orchestration branch, without starting an actual emulator."""
    manifest = gate.read_json(gate.MANIFEST)
    calls = []
    mutated = False

    def snapshot(_manifest):
        return {"fixture": "changed" if mutated else "original"}

    def run(check, output_dir, expected, collect_only):
        nonlocal mutated
        calls.append(check["id"])
        if mode == "fixture-mutation":
            mutated = True
        return {"id": check["id"], "kind": check["kind"], "status": "passed",
                "problems": [], "seconds": 0, "collected": []}

    monkeypatch.setattr(gate, "REPORT_ROOT", tmp_path)
    monkeypatch.setattr(gate, "snapshot_inputs", snapshot)
    monkeypatch.setattr(gate, "prerequisite_problems", lambda *_args:
                        ["missing legal ROM"] if mode == "missing-prerequisite" else [])
    monkeypatch.setattr(gate, "run_check", run)
    # Even with all requirement assertions satisfied, these three conditions must block.
    monkeypatch.setattr(gate, "evaluate_requirements", lambda *_args: [])
    args = ["--quick", "--quiet"] if mode == "quick" else ["--quiet"]
    assert gate.main(args) == 1
    slow_checks = {c["id"] for c in manifest["checks"] if c.get("slow")}
    assert not slow_checks.intersection(calls)
    report = json.loads(next(tmp_path.glob("*/automation.json")).read_text(encoding="utf-8"))
    assert report["automation_passed"] is False
    assert report["release_passed"] is False
