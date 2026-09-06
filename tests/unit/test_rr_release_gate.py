"""Synthetic verifier tests only; none of these records are gameplay evidence."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.rr.inventory import BINDING_ROLES, MODES, TIMING_SCENARIOS, build_inventory
from tools.rr.release import strict_json, verify

HERE = Path(__file__).resolve().parents[2] / "tools" / "rr"


def synthetic_manifest(root):
    """Create complete self-test evidence in a temporary directory, never a release result."""
    inventory = build_inventory()
    candidate = inventory["candidate"]
    candidate.update(candidate_id="SYNTHETIC-SELF-TEST", source_commit="a" * 40,
                     native_build_id="SYNTHETIC-SELF-TEST", layout_sha256="b" * 64,
                     capabilities_sha256="c" * 64,
                     postgame_checkpoints=["SYNTHETIC-NAMED-CHECKPOINT"])
    artifacts = {}
    def artifact(aid, kind, content):
        path = root / (aid + ".bin")
        path.write_bytes(content)
        artifacts[aid] = {"path": path.name, "kind": kind, "sha256": hashlib.sha256(content).hexdigest()}
        return aid
    for role in BINDING_ROLES:
        if role != "fixture":
            artifact(role, role, ("SYNTHETIC " + role).encode())
            candidate["bindings"][role] = artifacts[role]["sha256"]
    for mode in MODES:
        aid = "fixture_" + mode
        artifact(aid, "fixture", ("SYNTHETIC " + mode).encode())
        candidate["fixtures"][mode] = artifacts[aid]["sha256"]
    descriptor = {"game": "rr4.1", "abi": 2, "build_id": candidate["native_build_id"],
                  "layout_sha256": candidate["layout_sha256"],
                  "capabilities_sha256": candidate["capabilities_sha256"]}
    artifact("descriptor", "native_descriptor", json.dumps(descriptor).encode())
    artifact("trace", "trace", b"SYNTHETIC SELF TEST: NO EMULATOR OR GAMEPLAY CAPTURE")
    contexts = {}
    for mode in MODES:
        bound = {role: role if role != "fixture" else "fixture_" + mode for role in BINDING_ROLES}
        contexts[mode] = {"bindings": bound, "players": [
            {"player": player, "mode": mode, "rom": "rom", "patch": "patch",
             "companion_present": True, "native_descriptor": "descriptor"}
            for player in ("a", "b")]}
    def assertions(case):
        return [{"id": name, "status": "pass", "artifact_ids": ["trace"]} for name in case["assertions"]]
    records = []
    for case in inventory["cases"]:
        record = {"case_id": case["case_id"], "run_id": "SYNTHETIC-RUN", "mode": case["mode"],
                  "status": "pass", "attempt": 1, "capture_kind": "synthetic",
                  "bindings": deepcopy(contexts[case["mode"]]["bindings"]),
                  "assertions": assertions(case)}
        req = case["requirements"]
        if "meaningful_repetitions" in req:
            record["repetitions"] = [
                {"repetition_id": f"rep-{index:02d}", "status": "pass", "attempt": 1,
                 "scenario": req["timing_scenario"], "assertions": assertions(case),
                 "schedule": {"dispatch_offset_frames": index - 10, "latency_ms": index * 10,
                              "pause_frames": 0, "disconnect_at": "none", "input_pattern": "neutral"}}
                for index in range(req["meaningful_repetitions"])]
            record["attempt_count"] = len(record["repetitions"])
        if "normal_speed_wall_seconds" in req:
            record["observations"] = {
                "normal_speed_wall_seconds": 7200, "active_wall_seconds": 7200,
                "speed_multiplier_min": 1.0, "speed_multiplier_max": 1.0,
                "started_utc": "2026-01-01T00:00:00Z", "ended_utc": "2026-01-01T02:00:00Z",
                "scenario_counts": deepcopy(req["scenario_counts"])}
        if req.get("candidate_postgame_checkpoints"):
            record["observations"] = {"completed_checkpoints": list(candidate["postgame_checkpoints"])}
        records.append(record)
    evidence = {"schema_version": 1, "run_id": "SYNTHETIC-RUN", "purpose": "self_test",
                "candidate": {key: candidate[key] for key in (
                    "candidate_id", "source_commit", "game", "base_rom_md5", "native_abi",
                    "native_build_id", "layout_sha256", "capabilities_sha256")},
                "contexts": contexts, "artifacts": artifacts, "records": records,
                "accounting": {"retry_policy": "none", "omitted_attempts": 0,
                               "skipped_case_ids": [], "xfail_case_ids": [], "deselected_case_ids": [],
                               "record_count": len(records),
                               "selected_case_ids": [r["case_id"] for r in records],
                               "executed_case_ids": [r["case_id"] for r in records]}}
    return inventory, evidence


class GateTests(unittest.TestCase):
    def setUp(self):
        # Tests are contained in this agent's staging folder, including temporary artifacts.
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-test-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(HERE)
        self.inv, self.ev = synthetic_manifest(self.root)

    def check_fails(self, code=None):
        report = verify(self.inv, self.ev, self.root)
        self.assertFalse(report["verification_passed"])
        self.assertFalse(report["release_ready"])
        if code:
            self.assertIn(code, {item["code"] for item in report["errors"]}, report["errors"][:5])
        return report

    def timing_record(self):
        return next(record for record in self.ev["records"] if "repetitions" in record)

    def soak_record(self):
        return next(record for record in self.ev["records"] if record["case_id"].endswith("soak.normal_speed_2h"))

    def test_complete_synthetic_manifest_is_self_test_not_release_proof(self):
        report = verify(self.inv, self.ev, self.root)
        self.assertTrue(report["verification_passed"], report["errors"][:5])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["verdict"], "SELF_TEST_ONLY")
        self.assertEqual(report["summary"]["passed"], len(self.inv["cases"]))

    def test_twenty_distinct_timing_cases_in_each_mode(self):
        self.assertEqual(len(TIMING_SCENARIOS), 20)
        for mode in MODES:
            rows = [case for case in self.inv["cases"] if case["mode"] == mode and "meaningful_repetitions" in case["requirements"]]
            self.assertEqual(len(rows), 20)
            self.assertTrue(all(case["requirements"]["meaningful_repetitions"] == 20 for case in rows))

    def test_empty_evidence_is_missing_not_green(self):
        self.ev["records"] = []
        report = self.check_fails("evidence.missing_case")
        self.assertEqual(report["summary"]["missing"], len(self.inv["cases"]))

    def test_one_missing_case_fails_even_with_adjusted_record_count(self):
        self.ev["records"].pop()
        self.ev["accounting"]["record_count"] -= 1
        self.ev["accounting"]["executed_case_ids"].pop()
        self.check_fails("evidence.missing_case")

    def test_duplicate_case_cannot_retry_away_a_failure(self):
        extra = deepcopy(self.ev["records"][0])
        self.ev["records"][0]["status"] = "fail"
        self.ev["records"].append(extra)
        self.check_fails("evidence.duplicate_case")

    def test_mutation_of_bound_file_detected_without_mtime(self):
        path = self.root / self.ev["artifacts"]["client"]["path"]
        path.write_bytes(b"changed client bytes")
        self.check_fails("artifact.hash_drift")

    def test_bound_hash_must_match_candidate(self):
        self.inv["candidate"]["bindings"]["rom"] = "0" * 64
        self.check_fails("contract.mismatch")

    def test_unsupported_mode_in_record(self):
        self.ev["records"][0]["mode"] = "hardcore"
        self.check_fails("contract.mismatch")

    def test_mixed_mgm_pair_fails_context(self):
        self.ev["contexts"][MODES[0]]["players"][1]["mode"] = MODES[1]
        self.check_fails("contract.mismatch")

    def test_missing_patch_and_descriptor_are_not_fallback_success(self):
        player = self.ev["contexts"][MODES[0]]["players"][0]
        player["companion_present"] = False
        player.pop("native_descriptor")
        self.check_fails("native.descriptor_missing")

    def test_wrong_native_descriptor_rejected_even_with_new_artifact_hash(self):
        path = self.root / self.ev["artifacts"]["descriptor"]["path"]
        descriptor = json.loads(path.read_text())
        descriptor["abi"] = 1
        path.write_text(json.dumps(descriptor))
        self.ev["artifacts"]["descriptor"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.check_fails("contract.mismatch")

    def test_missing_assertion_fails(self):
        self.ev["records"][0]["assertions"].pop()
        self.check_fails("assertion.missing_duplicate_or_unknown")

    def test_unknown_uncertain_and_skipped_results_fail(self):
        for status in ("uncertain", "skip", "xfail", "unknown"):
            with self.subTest(status=status):
                self.ev["records"][0]["status"] = status
                self.check_fails("contract.mismatch")

    def test_assertion_without_capture_artifact_fails(self):
        self.ev["records"][0]["assertions"][0]["artifact_ids"] = []
        self.check_fails("assertion.no_artifact")

    def test_run_identity_must_match(self):
        self.ev["records"][0]["run_id"] = "different-run"
        self.check_fails("contract.mismatch")

    def test_candidate_cannot_remove_required_case(self):
        self.inv["cases"].pop()
        self.check_fails("inventory.missing_core_case")

    def test_candidate_cannot_weaken_twenty_repetitions(self):
        next(c for c in self.inv["cases"] if "meaningful_repetitions" in c["requirements"])["requirements"]["meaningful_repetitions"] = 1
        self.check_fails("inventory.weakened_or_changed_core_case")

    def test_unexpected_case_is_not_coverage(self):
        extra = deepcopy(self.ev["records"][0])
        extra["case_id"] = "rr41.default_mgm_off.ghost.not_declared"
        self.ev["records"].append(extra)
        self.check_fails("evidence.unexpected_case")

    def test_deselection_and_omitted_attempts_fail(self):
        self.ev["accounting"]["deselected_case_ids"] = [self.ev["records"][0]["case_id"]]
        self.ev["accounting"]["omitted_attempts"] = 1
        self.check_fails("contract.mismatch")

    def test_timing_exact_repeats_with_new_ids_do_not_count(self):
        record = self.timing_record()
        for rep in record["repetitions"]:
            rep["schedule"] = deepcopy(record["repetitions"][0]["schedule"])
        self.check_fails("timing.insufficient_distinct_schedules")

    def test_missing_or_failed_timing_repetition_fails(self):
        record = self.timing_record()
        record["repetitions"].pop()
        record["attempt_count"] -= 1
        record["repetitions"][0]["status"] = "fail"
        self.check_fails("timing.insufficient_repetitions")

    def test_repeated_attempt_number_is_rejected(self):
        self.timing_record()["repetitions"][0]["attempt"] = 2
        self.check_fails("contract.mismatch")

    def test_soak_requires_7200_actual_normal_speed_seconds(self):
        self.soak_record()["observations"]["normal_speed_wall_seconds"] = 7199
        self.check_fails("soak.insufficient_normal_speed")

    def test_soak_rejects_turbo_and_missing_scenarios(self):
        observations = self.soak_record()["observations"]
        observations["speed_multiplier_max"] = 4
        observations["scenario_counts"]["native_trades_completed"] = 0
        self.check_fails("soak.scenario_count")

    def test_soak_duration_cannot_exceed_recorded_interval(self):
        self.soak_record()["observations"]["ended_utc"] = "2026-01-01T00:00:10Z"
        self.check_fails("soak.interval")

    def test_postgame_names_must_be_locked_and_completed(self):
        self.inv["candidate"]["postgame_checkpoints"] = []
        self.check_fails("candidate.unresolved")

    def test_fixture_hashes_bound_separately_per_mode(self):
        self.ev["records"][0]["bindings"]["fixture"] = "fixture_" + MODES[1]
        self.check_fails("contract.mismatch")

    def test_parent_traversal_rejected(self):
        self.ev["artifacts"]["trace"]["path"] = "../outside.bin"
        self.check_fails("artifact.path_or_missing")

    def test_windows_absolute_and_unc_paths_rejected(self):
        for path in ("C:/outside.bin", "C:outside.bin", "\\\\server\\share\\capture.bin"):
            with self.subTest(path=path):
                self.ev["artifacts"]["trace"]["path"] = path
                self.check_fails("artifact.path_escape")

    def test_malformed_artifact_path_rejected_without_crashing(self):
        self.ev["artifacts"]["trace"]["path"] = "bad\x00name.bin"
        self.check_fails("artifact.path_or_missing")

    def test_link_escape_rejected(self):
        # The link and target both stay inside this agent's staging; target is outside evidence root.
        other = tempfile.TemporaryDirectory(prefix="synthetic-outside-", dir=HERE)
        self.addCleanup(other.cleanup)
        target = Path(other.name) / "outside.bin"
        target.write_bytes(b"outside evidence root")
        link = self.root / "escape"
        if os.name == "nt":
            # Junctions do not require Windows symlink privileges. Both directories are agent-owned.
            import _winapi
            _winapi.CreateJunction(str(target.parent), str(link))
        else:
            link.symlink_to(target.parent, target_is_directory=True)
        self.assertFalse((link / target.name).resolve().is_relative_to(self.root))
        self.ev["artifacts"]["trace"]["path"] = "escape/" + target.name
        self.check_fails("artifact.path_or_missing")

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for text in ('{"records": [], "records": []}', '{"duration": NaN}', '{"duration": Infinity}', '{"duration": 1e309}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)

    def test_malformed_extension_is_rejected_without_crashing(self):
        self.inv["cases"].append({"case_id": "rr41.bad.native.extension", "mode": [], "group": "native",
                                  "assertions": [], "requirements": []})
        self.check_fails("inventory.unsupported_case")

    def test_malformed_schedule_is_rejected_without_crashing(self):
        self.timing_record()["repetitions"][0]["schedule"]["disconnect_at"] = []
        self.check_fails("timing.invalid_schedule")

    def test_cli_writes_report_and_selftest_exit_is_nonzero(self):
        inv_path, ev_path, out_path = (self.root / name for name in ("inventory.json", "evidence.json", "report.json"))
        inv_path.write_text(json.dumps(self.inv))
        ev_path.write_text(json.dumps(self.ev))
        result = subprocess.run([sys.executable, str(HERE / "release.py"), "--inventory", str(inv_path),
                                 "--evidence", str(ev_path), "--output", str(out_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(out_path.read_text())
        self.assertTrue(report["verification_passed"])
        self.assertFalse(report["release_ready"])
        self.assertIn("SELF_TEST_ONLY", result.stdout)

    def test_cli_missing_evidence_is_not_green(self):
        result = subprocess.run([sys.executable, str(HERE / "release.py"), "--evidence", str(self.root / "absent.json")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["missing"], len(self.inv["cases"]))

    def test_cli_cannot_overwrite_referenced_artifact(self):
        inv_path, ev_path = self.root / "inventory.json", self.root / "evidence.json"
        inv_path.write_text(json.dumps(self.inv))
        ev_path.write_text(json.dumps(self.ev))
        artifact = self.root / self.ev["artifacts"]["rom"]["path"]
        original = artifact.read_bytes()
        result = subprocess.run([sys.executable, str(HERE / "release.py"), "--inventory", str(inv_path),
                                 "--evidence", str(ev_path), "--output", str(artifact)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(artifact.read_bytes(), original)

    def test_cli_cannot_overwrite_input_json(self):
        ev_path = self.root / "evidence.json"
        ev_path.write_text(json.dumps(self.ev))
        original = ev_path.read_bytes()
        result = subprocess.run([sys.executable, str(HERE / "release.py"), "--evidence", str(ev_path),
                                 "--output", str(ev_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(ev_path.read_bytes(), original)

    def test_cli_cannot_overwrite_hardlink_alias_of_artifact(self):
        inv_path, ev_path = self.root / "inventory.json", self.root / "evidence.json"
        inv_path.write_text(json.dumps(self.inv))
        ev_path.write_text(json.dumps(self.ev))
        artifact = self.root / self.ev["artifacts"]["rom"]["path"]
        alias = self.root / "output-alias.json"
        os.link(artifact, alias)
        original = artifact.read_bytes()
        result = subprocess.run([sys.executable, str(HERE / "release.py"), "--inventory", str(inv_path),
                                 "--evidence", str(ev_path), "--output", str(alias)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(artifact.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
