"""Gen 2 manifest contracts; synthetic results are MODEL, never cartridge evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import verify_gen2_release as gate  # noqa: E402
from coverage_map import main as coverage_main  # noqa: E402


def _lane(name):
    return next(lane for lane in gate.LANES if lane.name == name)


def test_required_phase_lanes_and_every_title_are_declared():
    names = [lane.name for lane in gate.LANES]
    assert names == [
        "unit", "source-build", "rom-layout", "lua-parse",
        "profile-generated-crystal", "profile-generated-gold", "profile-generated-silver",
        "species-generated", "evos-generated", "items-generated", "moves-generated", "charmap-generated",
        "map-names-generated", "engine-sites-generated", "checkpoint-generated",
        "area-map-generated", "encounters-generated", "statics-generated",
        "trainers-generated", "admission-generated", "coverage-map", "fixtures", "patch-build",
        "live-gates", "live-new-gates", "live-trade-gates", "duo-link", "duo-pairs", "release-evidence",
    ]
    assert gate.manifest_errors() == []
    for title in ("crystal", "gold", "silver"):
        assert _lane(f"profile-generated-{title}").argv[-3:] == ["--title", title, "--check"]
    assert "--check" in _lane("source-build").argv


def test_fixture_lane_declares_gold_wrong_save_control_as_input():
    assert "tests/fixtures/gen2/gold_battle_ot2.SaveRAM" in gate.PREREQUISITES["fixtures"]


def test_duo_matrix_cli_imports_repo_without_pythonpath(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, str(REPO / "tools/verify_gen2_release.py"), "--duo-matrix"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode in (0, 1), proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "duo matrix:" in proc.stdout, proc.stdout


def test_live_new_gates_lane_targets_the_p3b3a_inspect_driver():
    """P3b.3a landed lua/tests/gen2_inspect_gate.lua and tests/live/test_gen2_new_gates.py; this
    lane's argv still names that file (the live run is still what proves R-1/R-2/R-3/R-4/R-5g). The
    engine-site (U1/P3b.4), write-window (U2/P3b.5, Silver via O-23) and fixture-qualification rows
    the lane's full requirement mapping also needs are now bound by new_gates_errors() against
    tests/gen2_live_gate_requirements.json, so the lane is no longer UNIMPLEMENTED -- a gap in that
    binding fails run_lane before it ever spawns EmuHawk."""
    lane = _lane("live-new-gates")
    assert "tests/live/test_gen2_new_gates.py" in lane.argv
    assert (Path(__file__).resolve().parents[2] / "tests/live/test_gen2_new_gates.py").exists()
    assert "inspect" in lane.why
    assert "live-new-gates" not in gate.UNIMPLEMENTED
    assert "live-new-gates" in gate._SLOW
    assert gate.NEW_GATES in gate.PREREQUISITES["live-new-gates"]
    assert {"R-1", "R-2", "R-3", "R-5g"} <= set(gate.REQUIREMENTS["live-new-gates"])


def test_moves_regeneration_is_a_required_f5_source_lane():
    lane = _lane("moves-generated")
    assert lane.argv[1:] == ["tools/gen_gen2_moves.py", "--check"]
    assert gate.REQUIREMENTS[lane.name] == ["F-5"]
    assert lane.name not in gate._SLOW


def test_all_requirement_ids_are_mapped_without_deferred_rows_becoming_passes():
    ids = set(gate.REQUIREMENT_IDS)
    assert len(ids) == 53
    assert set().union(*(set(rows) for rows in gate.REQUIREMENTS.values())) == ids
    assert set(gate.CONDITIONAL_OR_DEFERRED) == {"W-3", "W-4", "C-5", "D-11", "N-3"}
    assert "R-2" in gate.REQUIREMENTS["live-new-gates"]
    assert set(gate.REQUIREMENTS["coverage-map"]) == ids
    assert set(gate.REQUIREMENTS["release-evidence"]) == ids
    assert "release-evidence" not in gate.UNIMPLEMENTED
    assert "tests/gen2_release_requirements.json" in gate.PREREQUISITES["release-evidence"]


def test_coverage_cli_selects_three_clean_artifacts_and_mapping_only():
    argv = _lane("coverage-map").argv
    assert argv[-2:] == ["--mode", "mapping"]
    selected = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--artifact-id"]
    assert selected == ["pokecrystal", "pokegold", "pokesilver"]
    assert "tests/gen2_release_requirements.json" not in argv
    assert "--protocol-section" in argv and argv[argv.index("--protocol-section") + 1] == "9"


@pytest.mark.parametrize("mutation", [None, "omit_targets", "omit_overlay_binding", "omit_ghost_binding", "swap_ghost_scope"])
def test_actual_coverage_argv_requires_explicit_native_target_policy(tmp_path, capsys, mutation):
    """Exercise the real validator through the manifest argv, using MODEL contract files."""
    requirement_ids = ["F-1", "C-3", "T-1", "T-2", "T-3", "T-4", "N-1", "N-2", "N-3"]
    protocol_ids = ["39", "40", "41", "42", "43", "47"]
    requirements = ["| id | Requirement | Oracle | S | M | P |", "|---|---|---|---|---|---|"]
    for identifier in requirement_ids:
        oracle = "— (SOURCE-only, P = —)" if identifier == "F-1" else "GAME"
        physical = "—" if identifier == "F-1" else "·"
        requirements.append(f"| {identifier} | Model contract {identifier} | {oracle} | · | · | {physical} |")
    protocol = "## 9. Model protocol contract\n" + "\n".join(f"{i}. Assertion {i}." for i in protocol_ids)
    paths = {"requirements": tmp_path / "requirements.md", "protocol": tmp_path / "protocol.md",
             "artifact_policy": tmp_path / "artifacts.json", "map": tmp_path / "coverage.md"}
    paths["requirements"].write_text("\n".join(requirements), encoding="utf-8")
    paths["protocol"].write_text(protocol, encoding="utf-8")
    bases = {"pokecrystal": "a" * 40, "pokegold": "b" * 40, "pokesilver": "c" * 40}
    paths["artifact_policy"].write_text(json.dumps({"outputs": {
        name: {"state": "BUILT", "sha1": digest} for name, digest in bases.items()
    }}), encoding="utf-8")
    pins = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items() if name != "map"}
    targets = {kind: {f"{title}_{kind}": {
        "state": "PLANNED", "digest": None, "base_artifact": base, "base_digest": bases[base],
    } for title, base in (("crystal", "pokecrystal"), ("gold", "pokegold"), ("silver", "pokesilver"))}
        for kind in ("overlay", "ghost")}
    rows = []
    identifiers = [*(f"requirement:{i}" for i in requirement_ids), *(f"protocol:9.{i}" for i in protocol_ids)]
    for identifier in identifiers:
        layers = ["SOURCE"] if identifier == "requirement:F-1" else ["SOURCE", "PHYSICAL"]
        artifacts = bases if identifier == "requirement:F-1" else targets["ghost" if identifier == "requirement:N-3" else "overlay"]
        rows.append({"id": identifier, "required_layers": layers, "mapping": {
            "status": "MAPPED", "stimulus": {"kind": "SOURCE" if layers == ["SOURCE"] else "NATURAL",
                                               "description": "Planned model fixture stimulus"},
            "artifacts": artifacts, "positive_control": "Known positive", "refusal_control": "Known refusal",
            "oracle": "Independent oracle", "receipt_marker": identifier, "lane": "planned-lane",
        }, "evidence": {layer: {"status": "OPEN", "reason": "Not run."} for layer in layers}})
    document = {"schema_version": 1, "input_sha256": pins, "rows": rows}
    paths["map"].write_text("<!-- COVERAGE_MAP_START -->\n```json\n" + json.dumps(document)
                           + "\n```\n<!-- COVERAGE_MAP_END -->", encoding="utf-8")
    argv = list(_lane("coverage-map").argv[2:])
    for flag, name in (("--map", "map"), ("--requirements", "requirements"),
                       ("--protocol", "protocol"), ("--artifact-policy", "artifact_policy")):
        argv[argv.index(flag) + 1] = str(paths[name])
    changed = []
    index = 0
    while index < len(argv):
        flag = argv[index]
        value = argv[index + 1] if index + 1 < len(argv) else ""
        if (mutation == "omit_targets" and flag in {"--planned-target", "--target-binding"}
                or mutation == "omit_overlay_binding" and flag == "--target-binding" and "requirement:C-3" in value
                or mutation == "omit_ghost_binding" and flag == "--target-binding" and value.startswith("requirement:N-3=")):
            index += 2
            continue
        if mutation == "swap_ghost_scope" and flag == "--target-binding" and value.startswith("requirement:N-3="):
            changed.extend((flag, value.replace("_ghost", "_overlay")))
            index += 2
            continue
        changed.append(flag)
        index += 1
    result = coverage_main(changed)
    output = capsys.readouterr()
    if mutation is not None:
        assert result == 1
    else:
        assert result == 0, output
        report = json.loads(output.out)
        assert report["mapping_complete"] and not report["evidence_complete"]
        assert len(report["unbuilt_artifacts"]) == 6
        changed[-1] = "closure"
        assert coverage_main(changed) == 1
        assert "unbuilt" in capsys.readouterr().out


def test_list_works_without_future_files_and_never_runs_a_lane(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "run_lane", lambda *_args, **_kwargs: pytest.fail("lane executed"))
    before = sorted(tmp_path.rglob("*"))
    assert gate.manifest_errors() == []
    assert gate.main(["--list"]) == 0
    out = capsys.readouterr().out
    for lane in gate.LANES:
        assert any(line.split() and line.split()[0] == lane.name for line in out.splitlines())
    assert out.count("requirements:") == len(gate.LANES)
    assert "GATE PASSED" not in out
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("mutation", [
    "missing_lane", "duplicate_lane", "missing_mapping", "omitted_requirement",
    "duplicate_requirement", "unknown_requirement", "empty_future_binding",
])
def test_manifest_mutations_fail_before_any_lane_runs(monkeypatch, capsys, mutation):
    if mutation == "missing_lane":
        monkeypatch.setattr(gate, "LANES", gate.LANES[1:])
    elif mutation == "duplicate_lane":
        monkeypatch.setattr(gate, "LANES", [*gate.LANES, gate.LANES[0]])
    elif mutation == "empty_future_binding":
        monkeypatch.setattr(gate, "LANES", [gate.Lane(lane.name, []) if lane.name == "release-evidence"
                                            else lane for lane in gate.LANES])
    else:
        rows = {name: list(ids) for name, ids in gate.REQUIREMENTS.items()}
        if mutation == "missing_mapping":
            del rows["live-new-gates"]
        elif mutation == "omitted_requirement":
            rows["live-new-gates"].remove("R-2")
        elif mutation == "duplicate_requirement":
            rows["live-new-gates"].append("R-2")
        else:
            rows["live-new-gates"].append("invented")
        monkeypatch.setattr(gate, "REQUIREMENTS", rows)
    monkeypatch.setattr(gate, "run_lane", lambda *_args, **_kwargs: pytest.fail("lane executed"))
    assert gate.main([]) == 1
    out = capsys.readouterr()
    assert "manifest invalid" in out.err
    assert "GATE PASSED" not in out.out


@pytest.mark.parametrize("selection", [["-k", "passing_subset"], ["--deselect=tests/x.py::test_x"],
                                      ["-m", "only_ready"]])
def test_pytest_deselection_is_rejected_in_manifest(monkeypatch, selection):
    original = _lane("unit")
    changed = gate.Lane("unit", [*original.argv, *selection])
    monkeypatch.setattr(gate, "LANES", [changed, *gate.LANES[1:]])
    assert any("deselection" in error for error in gate.manifest_errors())


def test_missing_script_fails_before_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    (tmp_path / "lua").mkdir()
    monkeypatch.setattr(gate.release_lanes, "run_lane",
                        lambda *_args, **_kwargs: pytest.fail("missing script executed"))
    ok, detail = gate.run_lane(_lane("lua-parse"), quiet=True)
    assert not ok
    assert "tools/lua_syntax_check.py" in detail


def test_missing_source_inputs_fail_before_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate.release_lanes, "run_lane",
                        lambda *_args, **_kwargs: pytest.fail("missing source executed"))
    ok, detail = gate.run_lane(_lane("source-build"), quiet=True)
    assert not ok
    assert "data/gen2_sources.lock.json" in detail
    assert "data/gen2/build_provenance.json" in detail
    assert "pokecrystal11.gbc" in detail


def test_fixtures_lane_cannot_pass_by_merely_adding_files(tmp_path):
    """Every prerequisite path present, but as junk bytes with no receipt or disclosure: RED, never vacuous."""
    for rel in gate.PREREQUISITES["fixtures"]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".SaveRAM"):
            target.write_bytes(b"\x00" * (0x8000 + 22))
        elif rel.endswith(".json"):
            target.write_text(json.dumps({"requirements": []}), encoding="utf-8")
        else:
            target.mkdir(exist_ok=True)
    errors = gate.fixtures_errors(tmp_path)
    assert any("gold_battle_ot2: undisclosed" in e for e in errors), errors
    assert any("crystal_battle_errand" in e and "missing" in e for e in errors), errors


@pytest.mark.parametrize("args", [["--quick"], ["--lane", "unit"]])
def test_partial_runs_never_print_release_success(monkeypatch, capsys, args):
    calls = []

    def passed(lane, quiet):
        calls.append(lane.name)
        return True, "synthetic MODEL pass"

    monkeypatch.setattr(gate, "run_lane", passed)
    assert gate.main(args) == 0
    out = capsys.readouterr().out
    assert "not a release verdict" in out
    assert "GATE PASSED" not in out
    if args == ["--quick"]:
        assert calls == [lane.name for lane in gate.LANES if lane.name not in gate._SLOW]
        assert set(calls).isdisjoint(gate.UNIMPLEMENTED)
    else:
        assert calls == ["unit"]


def test_full_skeleton_cannot_pass_when_source_lanes_are_green(monkeypatch, tmp_path, capsys):
    """Every other lane green; the fixtures lane runs its real binding against an empty tree and stays RED."""
    real_binding = gate.run_lane

    def source_passes(lane, quiet):
        if lane.name == "fixtures":
            return real_binding(lane, quiet)
        return True, "synthetic source/MODEL pass"

    assert gate.UNIMPLEMENTED == {}
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate.release_lanes, "run_lane", lambda *_a, **_k: pytest.fail("lane executed"))
    monkeypatch.setattr(gate, "run_lane", source_passes)
    assert gate.main([]) == 1
    out = capsys.readouterr().out
    assert "GATE FAILED" in out
    assert "missing prerequisites" in out
    assert "GATE PASSED" not in out


@pytest.mark.parametrize("outcome", ["skipped", "xfailed", "xpassed", "deselected", "error"])
def test_shared_accounting_rejects_nonpassing_pytest_outcomes(monkeypatch, outcome):
    proc = SimpleNamespace(returncode=0, stdout=f"3 passed, 1 {outcome} in 0.1s\n", stderr="")
    monkeypatch.setattr(gate.release_lanes.subprocess, "run", lambda *_args, **_kwargs: proc)
    ok, _detail = gate.run_lane(_lane("unit"), quiet=True)
    assert not ok
    assert not gate.ALLOWED_SKIPS


@pytest.mark.parametrize("stdout", ["", "3989 tests collected in 4.80s\n"])
def test_zero_execution_cannot_pass_the_gen2_binding(monkeypatch, stdout):
    proc = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(gate.release_lanes.subprocess, "run", lambda *_args, **_kwargs: proc)
    ok, detail = gate.run_lane(_lane("unit"), quiet=True)
    assert not ok
    assert "no passing tests executed" in detail


def test_process_start_failure_is_a_lane_failure(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("interpreter unavailable")

    monkeypatch.setattr(gate.release_lanes.subprocess, "run", unavailable)
    ok, detail = gate.run_lane(_lane("unit"), quiet=True)
    assert not ok
    assert "cannot execute lane" in detail


# --- H4: the release duo matrix (C<->C, G<->S, C<->G); every gap is RED -------------------------

REPO = Path(__file__).resolve().parents[2]
_CELL_FIXTURES = {"gen2_new": {"a": "crystal_battle", "b": "crystal_battle_ot2"},
                  "gen2_gold_silver": {"a": "gold_battle", "b": "silver_battle"},
                  "gen2_crystal_gold": {"a": "crystal_battle", "b": "gold_battle"}}


class _FakeRun:
    def assert_gen2_link_saved(self, results):  # pragma: no cover - only its presence matters
        return results


def _fake_duo(games=None, scenarios=None, require_oracle=True, family=None):
    """The slice of tools/e2e_duo.py the matrix reads: GAMES, SCENARIOS, DuoRun, contracts."""
    if games is None:
        games = {name: {"fixture": dict(fixtures)} for name, fixtures in _CELL_FIXTURES.items()}
    scenarios = {"link": {"oracle": "assert_gen2_link_saved"}} if scenarios is None else scenarios
    family = family or {}

    def contract(game):
        if family.get(game, "gen2_new") != "gen2_new":
            raise RuntimeError(f"{game}: no family evidence contract")
        return SimpleNamespace(require_oracle=require_oracle)

    return SimpleNamespace(
        GAMES=games, SCENARIOS=scenarios, DuoRun=_FakeRun, evidence_contract=contract,
        scenario_family=lambda game: family.get(game, "gen2_new" if game in games else game),
        scenarios_for=lambda game: list(scenarios))


def _lf_sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _write_doc(root, doc):
    (root / gate.DUO_MATRIX).write_text(json.dumps(doc), encoding="utf-8")


def _row(doc, rid):
    return next(row for row in doc["requirements"] if row["id"] == rid)


def _capture_key(text):
    """The ENGINE_CAPTURE {"key": ...} line's key, the way tools/verify_gen2_release.py reads it."""
    line = next(one for one in text.splitlines() if one.startswith("ENGINE_CAPTURE "))
    return json.loads(line[len("ENGINE_CAPTURE "):])["key"]


def _green_tree(tmp_path):
    """A fully receipted matrix built from the committed C<->C receipts: the known positive.

    Each case's fixture_sha256 is the REAL sha256 of its tests/fixtures/gen2/<case>.SaveRAM (review
    O16 F2) and the pydec receipt carries Codex's H5 PYDEC line (O16 F1), not the old bare PASS."""
    lock = json.loads((REPO / "data/gen2_sources.lock.json").read_text(encoding="utf-8"))
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data/gen2_sources.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (tmp_path / "tests/fixtures/gen2").mkdir(parents=True, exist_ok=True)
    doc = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    a_text = (REPO / "tests/fixtures/gen2/receipts/duo_link_cc_a_result.txt").read_text(encoding="utf-8")
    b_text = (REPO / "tests/fixtures/gen2/receipts/duo_link_cc_b_result.txt").read_text(encoding="utf-8")
    keys = {"a": _capture_key(a_text), "b": _capture_key(b_text)}
    source_text = {"a": a_text, "b": b_text}
    for row in doc["requirements"]:
        axes = row["axes"]
        axes["scenarios"] = ["link"]
        titles = {"a": axes["initiator"], "b": axes["partner"]}
        entries = {}
        for side in ("a", "b"):
            case = axes["fixtures"][side]
            fixture_bytes = (REPO / "tests/fixtures/gen2" / f"{case}.SaveRAM").read_bytes()
            (tmp_path / "tests/fixtures/gen2" / f"{case}.SaveRAM").write_bytes(fixture_bytes)
            header = {"attempt": 1, "case": case, "player": side,
                      "rom_sha1": lock["outputs"][f"poke{titles[side]}"]["sha1"], "scenario": "link",
                      "title": titles[side], "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest()}
            text = "\n".join("DUO_GEN2 " + json.dumps(header) if line.startswith("DUO_GEN2 ")
                             else line for line in source_text[side].splitlines()) + "\n"
            path = receipts / f"{row['id']}_{side}.txt"
            path.write_text(text, encoding="utf-8", newline="\n")
            entries[side] = {"path": path.relative_to(tmp_path).as_posix(), "sha256": _lf_sha(path)}
        pydec_text = ("attempt 1 of 1\n"
                      f"PYDEC: PASS a={keys['a']} b={keys['b']} area=route_29 "
                      f"titles={axes['initiator']}/{axes['partner']} status=alive\n")
        pydec_path = receipts / f"{row['id']}_pydec.txt"
        pydec_path.write_text(pydec_text, encoding="utf-8", newline="\n")
        entries["pydec"] = {"path": pydec_path.relative_to(tmp_path).as_posix(),
                            "sha256": _lf_sha(pydec_path)}
        row["proofs"] = [{"scenario": "link", "receipts": entries}]
    (tmp_path / "tests").mkdir(exist_ok=True)
    _write_doc(tmp_path, doc)
    return doc


def test_duo_link_lane_is_the_implemented_physical_matrix_lane():
    lane = _lane("duo-link")
    assert lane.argv[1:] == ["tools/verify_gen2_release.py", "--duo-matrix"]
    assert "duo-link" not in gate.UNIMPLEMENTED and "duo-link" in gate._SLOW
    assert gate.REQUIREMENTS["duo-link"] == ["D-1", "C-6g"]
    assert gate.DUO_MATRIX in gate.PREREQUISITES["duo-link"]
    assert sorted(gate.DUO_PAIRS) == [("crystal", "crystal"), ("crystal", "gold"), ("gold", "silver")]
    # The non-link P3b.7 scenarios are duo-pairs' pinned, red-until-receipted set.
    assert "D-2" in gate.REQUIREMENTS["duo-pairs"] and "gen2_ball_gate" in gate.DUO_PAIRS_SCENARIOS


def test_committed_matrix_is_red_exactly_where_a_pair_has_no_receipt():
    """Unreceipted cells stay red while newly recorded physical proofs can close their cells."""
    doc = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    errors = gate.duo_matrix_errors()
    for row in doc["requirements"]:
        mine = [error for error in errors if error.startswith(row["id"] + "/")]
        for proof in row["proofs"]:
            cell = row["id"] + "/" + proof["scenario"] + ":"
            ab_receipt_problems = [error for error in mine if error.startswith(cell)
                                   if "receipt" in error and "pydec receipt does not name" not in error]
            if proof["scenario"] == "gen2_faint":
                # Preimage hardening deliberately reopens the three archived memorial proofs.
                allowed = {f"{cell} {side} memorial receipt invalid: expected one MEMORIAL_PREIMAGE"
                           for side in ("a", "b")}
                ab_receipt_problems = [error for error in ab_receipt_problems if error not in allowed]
            assert not ab_receipt_problems, mine
        for scenario in row["axes"]["scenarios"]:
            if scenario not in {proof["scenario"] for proof in row["proofs"]}:
                assert f"{row['id']}/{scenario}: no receipt registered" in " ".join(mine)
    assert _row(doc, "duo.crystal.crystal")["proofs"], "the C<->C link PASS receipt is registered"


def test_fully_receipted_matrix_is_the_only_green(tmp_path):
    _green_tree(tmp_path)
    assert gate.duo_matrix_errors(tmp_path, _fake_duo()) == []


def _raise_no_contract(game):
    raise RuntimeError(f"{game}: no family evidence contract")


# Each gap names its own check, so every check is individually load-bearing (revert-tested).
_GAPS = {
    "pair_row_deleted": "release matrix pairs",
    "pairing_unregistered": "pairing gen2_gold_silver is not a gen2_new row",
    "extra_gen2_pairing": "gen2_silver_crystal: Gen 2 duo pairing in tools/e2e_duo.py is not in",
    "wrong_family": "pairing gen2_gold_silver is not a gen2_new row",
    "fixture_drift": "duo.gold.silver: tools/e2e_duo.py gen2_gold_silver fixtures",
    "scenario_unregistered": "duo.gold.silver/ball_gate: scenario not registered",
    "registered_scenario_undeclared": "registered scenario ball_gate is not in the release matrix",
    "link_undeclared": "required scenario(s) ['link'] not declared",
    "oracle_missing": "no post-result oracle (None)",
    "oracle_not_a_method": "no post-result oracle ('assert_nothing')",
    "oracle_not_required": "evidence contract does not require an oracle",
    "no_contract": "duo.gold.silver: gen2_gold_silver: no family evidence contract",
    "proof_emptied": "duo.gold.silver/link: no receipt registered",
    "receipt_missing": "duo.gold.silver/link: b receipt receipts/duo.gold.silver_b.txt missing",
    "receipt_unregistered": "duo.gold.silver/link: pydec receipt not registered",
    "receipt_edited": "duo.gold.silver/link: a receipt receipts/duo.gold.silver_a.txt sha256 differs",
    "verdict_fail": "duo.gold.silver/link: a receipt has no RESULT: PASS verdict",
    "pydec_fail": "duo.gold.silver/link: pydec receipt has no PYDEC: PASS verdict",
    "header_other_title": "duo.gold.silver/link: b receipt header does not name",
    "header_other_scenario": "duo.gold.silver/link: a receipt header does not name",
    "no_save_witness": "duo.gold.silver/link: b receipt has no SAVE_WITNESS line",
    # Review O16 (cx-4373a801) of H4 abec68c0 -- each finding gets its own red-first case.
    "f1_pydec_wrong_a_key": "duo.gold.silver/link: pydec receipt does not name this cell: a=",
    "f1_pydec_wrong_titles": "duo.gold.silver/link: pydec receipt does not name this cell: titles=",
    "f1_pydec_wrong_status": "duo.gold.silver/link: pydec receipt does not name this cell: status=",
    "f1_pydec_missing_area": "duo.gold.silver/link: pydec receipt does not name this cell: area=",
    "f1_pydec_old_content_free": "duo.gold.silver/link: pydec receipt does not name this cell",
    "f2_fixture_sha256_wrong": "duo.gold.silver/link: b receipt header does not name",
    "f3_unknown_title": "b: axes title 'ruby' has no 'pokeruby' entry in data/gen2_sources.lock.json",
    "f4_duplicate_proof_scenario": "duo.gold.silver: duplicate proof scenario(s) ['link']",
    "f4_undeclared_proof_scenario": "duo.gold.silver: proof scenario(s) ['whiteout'] not declared",
    "f5_malformed_row_no_axes": "duo.gold.silver: malformed row",
}


def _edit_pydec_token(key, new_value):
    def edit(text):
        return "\n".join(
            " ".join(f"{key}={new_value}" if part.startswith(f"{key}=") else part
                     for part in line.split(" ")) if line.startswith("PYDEC: PASS ") else line
            for line in text.splitlines()) + "\n"
    return edit


def _drop_pydec_token(key):
    def edit(text):
        return "\n".join(
            " ".join(part for part in line.split(" ") if not part.startswith(f"{key}="))
            if line.startswith("PYDEC: PASS ") else line
            for line in text.splitlines()) + "\n"
    return edit


def _edit_header_field(key, new_value):
    def edit(text):
        out = []
        for line in text.splitlines():
            if line.startswith("DUO_GEN2 "):
                header = json.loads(line[len("DUO_GEN2 "):])
                header[key] = new_value
                line = "DUO_GEN2 " + json.dumps(header)
            out.append(line)
        return "\n".join(out) + "\n"
    return edit


@pytest.mark.parametrize("mutation", list(_GAPS))
def test_every_matrix_gap_is_red(tmp_path, mutation):
    doc = _green_tree(tmp_path)
    duo = _fake_duo()
    gs = _row(doc, "duo.gold.silver")
    receipts = gs["proofs"][0]["receipts"]

    def rewrite(side, edit):
        path = tmp_path / receipts[side]["path"]
        path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        receipts[side]["sha256"] = _lf_sha(path)  # re-pinned: only the semantic check can catch it

    if mutation == "pair_row_deleted":
        doc["requirements"].remove(gs)
        del duo.GAMES["gen2_gold_silver"]
    elif mutation == "pairing_unregistered":
        del duo.GAMES["gen2_gold_silver"]
    elif mutation == "extra_gen2_pairing":
        duo.GAMES["gen2_silver_crystal"] = {"fixture": {"a": "silver_battle", "b": "crystal_battle"}}
    elif mutation == "wrong_family":
        duo = _fake_duo(family={"gen2_gold_silver": "gen1_new"})
    elif mutation == "fixture_drift":
        duo.GAMES["gen2_gold_silver"]["fixture"]["b"] = "silver_town"
    elif mutation == "scenario_unregistered":
        gs["axes"]["scenarios"].append("ball_gate")
    elif mutation == "registered_scenario_undeclared":
        duo.SCENARIOS["ball_gate"] = {"oracle": "assert_gen2_link_saved"}
    elif mutation == "link_undeclared":
        # Dropped from BOTH registry and matrix: otherwise the matrix would be zero cells, green.
        duo.SCENARIOS.clear()
        for row in doc["requirements"]:
            row["axes"]["scenarios"] = []
    elif mutation == "oracle_missing":
        duo.SCENARIOS["link"] = {}
    elif mutation == "oracle_not_a_method":
        duo.SCENARIOS["link"] = {"oracle": "assert_nothing"}
    elif mutation == "oracle_not_required":
        duo = _fake_duo(require_oracle=False)
    elif mutation == "no_contract":
        duo.evidence_contract = _raise_no_contract
    elif mutation == "proof_emptied":
        gs["proofs"] = []
    elif mutation == "receipt_missing":
        (tmp_path / receipts["b"]["path"]).unlink()
    elif mutation == "receipt_unregistered":
        del receipts["pydec"]
    elif mutation == "receipt_edited":
        path = tmp_path / receipts["a"]["path"]
        path.write_text(path.read_text(encoding="utf-8") + "X\n", encoding="utf-8")
    elif mutation == "verdict_fail":
        rewrite("a", lambda text: text.replace("RESULT: PASS", "RESULT: FAIL"))
    elif mutation == "pydec_fail":
        rewrite("pydec", lambda text: text.replace("PYDEC: PASS", "PYDEC: FAIL"))
    elif mutation == "header_other_title":
        rewrite("b", lambda text: text.replace('"title": "silver"', '"title": "gold"'))
    elif mutation == "header_other_scenario":
        rewrite("a", lambda text: text.replace('"scenario": "link"', '"scenario": "faint"'))
    elif mutation == "no_save_witness":
        rewrite("b", lambda text: "\n".join(line for line in text.splitlines()
                                            if not line.startswith("SAVE_WITNESS ")))
    elif mutation == "f1_pydec_wrong_a_key":
        rewrite("pydec", _edit_pydec_token("a", "WRONGKEY"))
    elif mutation == "f1_pydec_wrong_titles":
        rewrite("pydec", _edit_pydec_token("titles", "gold/gold"))
    elif mutation == "f1_pydec_wrong_status":
        rewrite("pydec", _edit_pydec_token("status", "dead"))
    elif mutation == "f1_pydec_missing_area":
        rewrite("pydec", _drop_pydec_token("area"))
    elif mutation == "f1_pydec_old_content_free":
        rewrite("pydec", lambda text: "attempt 1 of 1\nPYDEC: PASS asserted scenario facts\n")
    elif mutation == "f2_fixture_sha256_wrong":
        rewrite("b", _edit_header_field("fixture_sha256", "0" * 64))
    elif mutation == "f3_unknown_title":
        gs["axes"]["partner"] = "ruby"
    elif mutation == "f4_duplicate_proof_scenario":
        gs["proofs"] = gs["proofs"] + [gs["proofs"][0]]
    elif mutation == "f4_undeclared_proof_scenario":
        gs["proofs"].append({"scenario": "whiteout", "receipts": {}})
    elif mutation == "f5_malformed_row_no_axes":
        del gs["axes"]
    _write_doc(tmp_path, doc)
    errors = gate.duo_matrix_errors(tmp_path, duo)
    assert any(_GAPS[mutation] in error for error in errors), (mutation, errors)


def test_duo_matrix_cli_exit_follows_the_gaps(monkeypatch, capsys):
    monkeypatch.setattr(gate, "duo_matrix_errors", lambda: ["duo.gold.silver/link: no receipt"])
    assert gate.main(["--duo-matrix"]) == 1
    assert "RED  duo.gold.silver/link" in capsys.readouterr().out
    monkeypatch.setattr(gate, "duo_matrix_errors", lambda: [])
    assert gate.main(["--duo-matrix"]) == 0
    assert "RECEIPTED" in capsys.readouterr().out


# --- H4b: live-new-gates receipt binding (U1 engine-site, U2 write-window incl. O-23, fixture
# qualification); no emulator; every gap is RED --------------------------------------------------

def _copy_new_gates_tree(tmp_path):
    """A byte-identical copy of the committed new-gates receipts and their manifest -- the known
    positive, safe to mutate without touching the real tree."""
    doc = json.loads((REPO / gate.NEW_GATES).read_text(encoding="utf-8"))
    for row in doc["requirements"]:
        entry = row["proofs"][0]["receipts"]["receipt"]
        src, dst = REPO / entry["path"], tmp_path / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        if row["axes"]["kind"] == "qualification":
            fixture = row["axes"]["fixture"] + ".SaveRAM"
            (tmp_path / "tests/fixtures/gen2" / fixture).write_bytes(
                (REPO / "tests/fixtures/gen2" / fixture).read_bytes())
        if row["axes"]["kind"] in ("panel_gate", "sfx_gate", "phone_gate"):
            fixture = json.loads(src.read_text(encoding="utf-8"))["fixture"] + ".SaveRAM"
            for rel in ("tests/fixtures/gen2/" + fixture, "data/gen2/overlay_provenance.json"):
                (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / rel).write_bytes((REPO / rel).read_bytes())
        if row["axes"]["kind"] == "w6_gate":
            legs = json.loads(src.read_text(encoding="utf-8"))["legs"].values()
            for rel in ["tests/fixtures/gen2/" + leg["fixture"] + ".SaveRAM" for leg in legs] + [
                    "data/gen2/overlay_provenance.json"]:
                (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / rel).write_bytes((REPO / rel).read_bytes())
    (tmp_path / gate.NEW_GATES).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _new_gates_row(doc, rid):
    return next(row for row in doc["requirements"] if row["id"] == rid)


def _repin(tmp_path, entry):
    entry["sha256"] = _lf_sha(tmp_path / entry["path"])


def test_new_gates_lane_is_the_implemented_receipt_lane():
    lane = _lane("live-new-gates")
    assert "live-new-gates" not in gate.UNIMPLEMENTED
    assert lane.name in gate._SLOW
    assert gate.NEW_GATES in gate.PREREQUISITES["live-new-gates"]
    assert "tests/fixtures/gen2/receipts" in gate.PREREQUISITES["live-new-gates"]


def test_committed_new_gates_tree_is_fully_green():
    """The real tree today: every U1/U2/qualification row bound, pinned and PHYSICAL. One named, known gap:
    the W6 Silver U1 leg's clock setup predates clock-setup-v1 (it assumed a 10:00 start where the save holds
    09:58:55) and stays RED until W6 Silver re-runs on the fixed day_clock. Any other gap fails here."""
    errors = gate.new_gates_errors()
    known = [e for e in errors if e.startswith("new-gates.w6.silver: w6 gate leg u1: clock setup")]
    assert errors == known and len(known) <= 1, errors


def test_copied_new_gates_tree_is_also_green(tmp_path):
    _copy_new_gates_tree(tmp_path)
    errors = gate.new_gates_errors(tmp_path)   # the same single known gap as the committed tree (W6 Silver clock)
    assert all(e.startswith("new-gates.w6.silver: w6 gate leg u1: clock setup") for e in errors) and len(errors) <= 1


def test_new_gates_manifest_missing_is_red(tmp_path):
    assert gate.new_gates_errors(tmp_path) == [f"{gate.NEW_GATES} missing"]


def test_o23_row_reuses_golds_receipt_for_silver():
    """docs/gen2/REVIEW_RECORD.md O-23: Silver's row is Gold's own receipt file, not a copy."""
    doc = json.loads((REPO / gate.NEW_GATES).read_text(encoding="utf-8"))
    gold = _new_gates_row(doc, "new-gates.write-window.gold")["proofs"][0]["receipts"]["receipt"]
    silver = _new_gates_row(doc, "new-gates.write-window.silver")["proofs"][0]["receipts"]["receipt"]
    assert gold["path"] == silver["path"] == "tests/fixtures/gen2/receipts/gold.write_window.json"
    assert gold["sha256"] == silver["sha256"]


# Each gap names its own check, so every check is individually load-bearing (revert-tested).
_NEW_GATE_GAPS = {
    "proof_emptied": "no receipt registered (an empty proof is a release blocker)",
    "receipt_unregistered": "receipt not registered",
    "receipt_missing": "missing",
    "receipt_edited": "sha256 differs from its pin",
    "engine_site_flipped": "differs from the pack or has no live hit",
    "write_window_flipped": "not a read-back HP-1",
    "o23_checkpoint_diverges": "write-window receipt proved other checkpoint rows than this pack's",
    "qualification_failed": "fixture qualification receipt is not a passed run",
    "qualification_fixture_swapped": "does not confirm",
    "unknown_kind": "no validator for receipt kind",
    "panel_gate_stale_overlay": "another overlay build than the published one",
    "panel_gate_no_margin": "no positive minimum-SP margin",
    "panel_gate_fixture_and_hash_absent": "does not bind the committed fixture's bytes",
    "sfx_gate_stale_overlay": "sfx gate receipt proves another overlay build",
    "sfx_gate_context_late": "sfx gate context text did not play within its deadline",
    "sfx_gate_context_missing": "sfx gate context battle_anim did not play within its deadline",
    "sfx_gate_battle_gap": "battle worst-case service gap is missing or past the deadline",
    "sfx_gate_reset_played": "sfx gate reset did not drop a pending request",
    "w6_gate_violation": "w6 gate leg u1 saw a mailbox writer outside SLink code",
    "w6_gate_control_missed": "w6 gate leg sfx known-positive control did not fire",
    "w6_gate_leg_missing": "w6 gate receipt does not cover the panel, sfx and u1 legs",
    "w6_gate_leg_fixture": "w6 gate leg u1 does not bind the committed fixture's bytes",
    "phone_gate_early_ring": "phone gate case town did not ring SLink after its step",
    "phone_gate_save_unproven": "phone gate save did not prove a real save left the SRAM phone id 0",
    "phone_gate_native_late": "phone gate native call did not keep precedence",
    "phone_gate_stale_overlay": "phone gate receipt proves another overlay build",
}


@pytest.mark.parametrize("mutation", list(_NEW_GATE_GAPS))
def test_every_new_gate_gap_is_red(tmp_path, mutation):
    doc = _copy_new_gates_tree(tmp_path)
    row = lambda rid: _new_gates_row(doc, rid)  # noqa: E731

    if mutation == "proof_emptied":
        row("new-gates.engine-sites.crystal")["proofs"] = []
    elif mutation == "receipt_unregistered":
        del row("new-gates.engine-sites.crystal")["proofs"][0]["receipts"]["receipt"]
    elif mutation == "receipt_missing":
        entry = row("new-gates.engine-sites.crystal")["proofs"][0]["receipts"]["receipt"]
        (tmp_path / entry["path"]).unlink()
    elif mutation == "receipt_edited":
        entry = row("new-gates.engine-sites.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif mutation == "engine_site_flipped":
        entry = row("new-gates.engine-sites.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        run = receipt["runs"][0] if "runs" in receipt else receipt   # card U1G: a v2 receipt's first run
        name = sorted(run["proven"])[0]
        raw = bytearray(bytes.fromhex(run["sites"][name]["expected_hex"]))
        raw[0] ^= 0x01
        run["sites"][name]["expected_hex"] = raw.hex()
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "write_window_flipped":
        entry = row("new-gates.write-window.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        party = receipt["runs"]["town"]["write"]["party"]
        raw = bytearray(bytes.fromhex(party["written_hex"]))
        raw[0] ^= 0x01
        party["written_hex"] = raw.hex()
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "o23_checkpoint_diverges":
        entry = row("new-gates.write-window.silver")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["checkpoint"]["anchors"]["ow_player_input"]["address"] += 2
        path.write_text(json.dumps(receipt), encoding="utf-8")
        # The mutated file is Gold's own receipt (O-23 shares it): re-pin both rows that name it so
        # only the checkpoint mismatch fires, not an unrelated sha256 drift on Gold's own row.
        _repin(tmp_path, entry)
        _repin(tmp_path, row("new-gates.write-window.gold")["proofs"][0]["receipts"]["receipt"])
    elif mutation == "qualification_failed":
        entry = row("new-gates.qualification.crystal_town")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["passed"] = False
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "qualification_fixture_swapped":
        entry = row("new-gates.qualification.crystal_town")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["fixtures"][0]["name"] = "crystal_battle"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "unknown_kind":
        row("new-gates.engine-sites.crystal")["axes"]["kind"] = "badge_sites"
    elif mutation == "panel_gate_stale_overlay":
        # A rebuilt overlay (a new published sha1) leaves the old receipt proving the old build.
        path = tmp_path / "data/gen2/overlay_provenance.json"
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["outputs"]["pokecrystal"]["sha1"] = "0" * 40
        path.write_text(json.dumps(provenance), encoding="utf-8")
    elif mutation == "sfx_gate_stale_overlay":
        path = tmp_path / "data/gen2/overlay_provenance.json"
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["outputs"]["pokegold"]["sha1"] = "0" * 40
        path.write_text(json.dumps(provenance), encoding="utf-8")
    elif mutation == "panel_gate_fixture_and_hash_absent":
        # None == None must not read as a bound fixture (Codex, P4.1g review).
        entry = row("new-gates.panel.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        del receipt["fixture"], receipt["fixture_sha256"]
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation.startswith("sfx_gate_") and mutation != "sfx_gate_stale_overlay":
        entry = row("new-gates.sfx.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "sfx_gate_context_late":
            receipt["contexts"]["text"]["played"] = receipt["contexts"]["text"]["posted"] + receipt["deadline_frames"] + 1
        elif mutation == "sfx_gate_context_missing":
            del receipt["contexts"]["battle_anim"]
        elif mutation == "sfx_gate_battle_gap":
            receipt["contexts"]["battle_anim"]["battle_service_gap"] = receipt["deadline_frames"] + 1
        else:
            receipt["reset"]["played_id"] = receipt["reset"]["dropped"]
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "phone_gate_stale_overlay":
        path = tmp_path / "data/gen2/overlay_provenance.json"
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["outputs"]["pokecrystal"]["sha1"] = "0" * 40
        path.write_text(json.dumps(provenance), encoding="utf-8")
    elif mutation.startswith("phone_gate_"):
        entry = row("new-gates.phone.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        cases = receipt["cases"]
        if mutation == "phone_gate_early_ring":
            cases["town"]["ring"]["frame"] = cases["town"]["step_at"] - 1
        elif mutation == "phone_gate_save_unproven":
            cases["save"]["extra"]["sram_changed_bytes"] = 0
        else:
            cases["native"]["extra"]["native_ring"]["frame"] = cases["native"]["ring"]["frame"] + 1
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation.startswith("w6_gate_"):
        entry = row("new-gates.w6.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "w6_gate_violation":
            receipt["legs"]["u1"]["violation_count"] = 1
        elif mutation == "w6_gate_control_missed":
            receipt["legs"]["sfx"]["control"]["native_caught"] = False
        elif mutation == "w6_gate_leg_missing":
            del receipt["legs"]["panel"]
        else:
            receipt["legs"]["u1"]["fixture_sha256"] = "0" * 64
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
    elif mutation == "panel_gate_no_margin":
        entry = row("new-gates.panel.crystal")["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["minimum_sp"]["margin_bytes"] = 0
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)

    (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    errors = gate.new_gates_errors(tmp_path)
    assert any(_NEW_GATE_GAPS[mutation] in error for error in errors), (mutation, errors)


def test_new_gates_cli_exit_follows_the_gaps(monkeypatch, capsys):
    monkeypatch.setattr(gate, "new_gates_errors", lambda: ["new-gates.x: no receipt"])
    assert gate.main(["--new-gates"]) == 1
    assert "RED  new-gates.x" in capsys.readouterr().out
    monkeypatch.setattr(gate, "new_gates_errors", lambda: [])
    assert gate.main(["--new-gates"]) == 0
    assert "PHYSICAL" in capsys.readouterr().out


def test_new_gates_precheck_blocks_run_lane_before_pytest(monkeypatch):
    monkeypatch.setattr(gate, "new_gates_errors", lambda: ["new-gates.x: gap"])
    monkeypatch.setattr(gate.release_lanes, "run_lane",
                        lambda *_args, **_kwargs: pytest.fail("pytest spawned despite the gap"))
    ok, detail = gate.run_lane(_lane("live-new-gates"), quiet=True)
    assert not ok
    assert detail == "new-gates.x: gap"


def test_pydec_end_status_is_per_scenario():
    """link must end alive; gen2_faint may end dead or memorial (the memorialize NACK lets the
    server finish the pair), never alive."""
    axes = {"initiator": "gold", "partner": "silver"}
    keys = {"a": "AAAA:1111:01", "b": "BBBB:2222:02"}

    def errs(scenario, status):
        line = f"PYDEC: PASS a={keys['a']} b={keys['b']} area=route_29 titles=gold/silver status={status}"
        return gate._pydec_cell_errors([line], scenario, axes, keys)

    assert errs("link", "alive") == []
    assert errs("link", "memorial") != []
    assert errs("gen2_faint", "dead") == [] and errs("gen2_faint", "memorial") == []
    assert errs("gen2_faint", "alive") != []


def _admission_cell(tmp_path):
    doc = _green_tree(tmp_path)
    row = _row(doc, "duo.crystal.crystal")
    proof, axes = row["proofs"][0], row["axes"]
    lock = json.loads((tmp_path / "data/gen2_sources.lock.json").read_text())["outputs"]
    rom = lock["pokecrystal11"]["sha1"]
    text = {}
    a = tmp_path / proof["receipts"]["a"]["path"]
    text["a"] = a.read_text().replace('"scenario": "link"', '"scenario": "gen2_admit_wrong_rom"')
    records = [
        ("DUO_GEN2", {"player": "b", "scenario": "gen2_admit_wrong_rom", "title": "crystal",
                       "rom_sha1": rom, "expect_admission": "refused", "attempt": 1}),
        ("ADMISSION_REFUSED", {"frame": 1, "rom_sha1": rom, "client": False,
                               "console": "refused (production admission): ROM sha1"}),
        ("NO_TRAFFIC", {"frame": 601, "frames": 600, "tx": 0}),
        ("CARTRAM_UNCHANGED", {"before": "a" * 64, "after": "a" * 64}),
        ("RECEIPT", {"schema": "gen2-duo-admit-wrong-rom-v1", "expect_admission": "refused",
                     "player": "b", "scenario": "gen2_admit_wrong_rom", "title": "crystal",
                     "rom_sha1": rom, "attempt": 1}),
    ]
    text["b"] = "\n".join(tag + " " + json.dumps(value) for tag, value in records) + "\nRESULT: PASS\n"
    text["pydec"] = ("PYDEC: PASS scenario=gen2_admit_wrong_rom a=admitted b=refused area=none "
                     f"titles=crystal/crystal status=refused rom_b={rom}\n")
    return proof, axes, lock, text


def _check_admission_cell(tmp_path, proof, axes, lock, text, scenario="gen2_admit_wrong_rom"):
    for side, body in text.items():
        entry = proof["receipts"][side]
        path = tmp_path / entry["path"]
        path.write_text(body, encoding="utf-8")
        entry["sha256"] = _lf_sha(path)
    return gate._receipt_errors(tmp_path, proof, scenario, axes, lock)


def test_wrong_rom_matrix_accepts_only_explicit_refused_half(tmp_path):
    proof, axes, lock, text = _admission_cell(tmp_path)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text) == []


@pytest.mark.parametrize("mutation", ["no_refusal", "client", "traffic", "cart", "rom", "title",
    "receipt", "save", "hello", "short_hold", "admitted_save", "pydec_status", "pydec_rom",
    "pydec_scenario", "pydec_side", "malformed", "malformed_header", "order", "duplicate"])
def test_wrong_rom_matrix_refuses_rebound_evidence(tmp_path, mutation):
    proof, axes, lock, text = _admission_cell(tmp_path)
    if mutation in ("no_refusal", "receipt"):
        prefix = "ADMISSION_REFUSED " if mutation == "no_refusal" else "RECEIPT "
        text["b"] = "\n".join(line for line in text["b"].splitlines() if not line.startswith(prefix))
    elif mutation == "client":
        text["b"] = text["b"].replace('"client": false', '"client": true')
    elif mutation == "traffic":
        text["b"] = text["b"].replace('"tx": 0', '"tx": 1')
    elif mutation == "cart":
        text["b"] = text["b"].replace('"after": "' + "a" * 64, '"after": "' + "b" * 64)
    elif mutation == "rom":
        text["b"] = text["b"].replace(lock["pokecrystal11"]["sha1"], lock["pokecrystal"]["sha1"])
    elif mutation == "title":
        text["b"] = text["b"].replace('"title": "crystal"', '"title": "gold"')
    elif mutation in ("save", "hello"):
        text["b"] += ("SAVE_WITNESS" if mutation == "save" else "HELLO") + " {}\n"
    elif mutation == "short_hold":
        text["b"] = text["b"].replace('"frames": 600', '"frames": 1')
    elif mutation == "admitted_save":
        text["a"] = "\n".join(line for line in text["a"].splitlines() if not line.startswith("SAVE_WITNESS "))
    elif mutation == "malformed":
        text["b"] = text["b"].replace('"client": false', '"client": invalid')
    elif mutation == "malformed_header":
        text["b"] = text["b"].replace('"player": "b"', '"player": invalid', 1)
    elif mutation == "order":
        rows = text["b"].splitlines()
        rows[1], rows[2] = rows[2], rows[1]
        text["b"] = "\n".join(rows)
    elif mutation == "duplicate":
        text["b"] += next(line for line in text["b"].splitlines() if line.startswith("NO_TRAFFIC ")) + "\n"
    else:
        key, value = {"pydec_status": ("status", "alive"), "pydec_rom": ("rom_b", "0" * 40),
                      "pydec_scenario": ("scenario", "link"), "pydec_side": ("a", "refused")}[mutation]
        text["pydec"] = _edit_pydec_token(key, value)(text["pydec"])
    assert _check_admission_cell(tmp_path, proof, axes, lock, text)


@pytest.mark.parametrize("scenario", ["link", "gen2_faint"])
def test_refused_half_exception_does_not_extend_to_capture_scenarios(tmp_path, scenario):
    proof, axes, lock, text = _admission_cell(tmp_path)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, scenario)


def _reconnect_cell(tmp_path):
    doc = _green_tree(tmp_path)
    row = _row(doc, "duo.crystal.crystal")
    proof, axes = row["proofs"][0], row["axes"]
    lock = json.loads((tmp_path / "data/gen2_sources.lock.json").read_text())["outputs"]
    keys = {"a": "1234:5678:00", "b": "1234:5678:01"}
    seeds = {"same_save": b"s" * 32790,
             "wrong_save": (REPO / "tests/fixtures/gen2/crystal_battle_ot2.SaveRAM").read_bytes()}
    proof["staged_saves"] = {}
    for phase, raw in seeds.items():
        path = tmp_path / f"{phase}.SaveRAM"
        path.write_bytes(raw)
        proof["staged_saves"][phase] = {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    proof["staged_saves"]["wrong_save"]["case"] = "crystal_battle_ot2"
    text = {}
    for side in ("a", "b", "a_same_save", "a_wrong_save"):
        player = "b" if side == "b" else "a"
        phase = side[2:] if side.startswith("a_") else "initial"
        fixture = axes["fixtures"][player] if phase == "initial" else "crystal_battle"
        head = {"player": player, "scenario": "gen2_reconnect", "title": "crystal", "case": fixture,
                "rom_sha1": lock["pokecrystal"]["sha1"], "attempt": 1,
                "fixture_sha256": gate._fixture_sha256(tmp_path, fixture) if phase == "initial"
                else proof["staged_saves"][phase]["sha256"]}
        records = [("DUO_GEN2", head), ("CLIENT", {"production_admitted": True}),
                   ("BOOTED", {}), ("HELLO", {"ot_id": 46401})]
        receipt = {**head, "schema": "gen2-duo-reconnect-v1", "phase": phase}
        if phase == "initial":
            records += [("ENGINE_CAPTURE", {"key": keys[player]}),
                        ("SAVE_WITNESS", {"saveram_bytes": 32790,
                          "cartram_sha256": hashlib.sha256(seeds["same_save"][:32768]).hexdigest()}),
                        ("RECONNECT_READY", {"phase": "initial", "player": player, "key": keys[player]})]
            if player == "b":
                records.append(("B_STAYED", {"hellos": 1, "force_faint": 0, "box_mon": 0}))
        else:
            detail = {"phase": phase, "hellos": 1, "expected_key": keys["a"], "linked": phase == "same_save"}
            records.append(("RECONNECT_HELLO", detail))
            receipt.update(detail)
            if phase == "wrong_save":
                records += [("RX_TEXT", {"cmd": "hud_show", "text": "[x] WRONG SAVE: slot A"}),
                            ("WRONG_SAVE_HUD", {"text": "[x] WRONG SAVE: slot A"})]
        if side != "a":
            records.append(("RECEIPT", receipt))
        text[side] = "\n".join(tag + " " + json.dumps(value) for tag, value in records) + "\n"
        if side != "a":
            text[side] += "RESULT: PASS\n"
        proof["receipts"][side] = {"path": f"receipts/{side}.txt"}
    text["pydec"] = (f"PYDEC: PASS scenario=gen2_reconnect a={keys['a']} b={keys['b']} "
                     "area=route_29 titles=crystal/crystal status=alive\n")
    return proof, axes, lock, text


def test_reconnect_matrix_binds_every_phase_and_staged_save(tmp_path):
    proof, axes, lock, text = _reconnect_cell(tmp_path)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect") == []


def _scratch_reconnect_cell(tmp_path, offset, *, title="crystal"):
    proof, axes, lock, text = _reconnect_cell(tmp_path)
    if title != "crystal":
        axes["initiator"], axes["fixtures"]["a"] = title, f"{title}_battle"
        wrong_case = f"{title}_battle_ot2"
        wrong = (REPO / f"tests/fixtures/gen2/{wrong_case}.SaveRAM").read_bytes()
        (tmp_path / f"tests/fixtures/gen2/{wrong_case}.SaveRAM").write_bytes(wrong)
        (tmp_path / "wrong_save.SaveRAM").write_bytes(wrong)
        proof["staged_saves"]["wrong_save"].update(case=wrong_case, sha256=hashlib.sha256(wrong).hexdigest())
        for side in ("a", "a_same_save", "a_wrong_save"):
            text[side] = text[side].replace('"title": "crystal"', f'"title": "{title}"').replace(
                '"case": "crystal_battle"', f'"case": "{title}_battle"').replace(
                lock["pokecrystal"]["sha1"], lock[f"poke{title}"]["sha1"])
        text["a"] = _edit_header_field("fixture_sha256", gate._fixture_sha256(tmp_path, f"{title}_battle"))(text["a"])
        text["a_wrong_save"] = _edit_header_field("fixture_sha256", hashlib.sha256(wrong).hexdigest())(text["a_wrong_save"])
        text["pydec"] = _edit_pydec_token("titles", f"{title}/crystal")(text["pydec"])
    baseline = (tmp_path / "same_save.SaveRAM").read_bytes()
    (tmp_path / "initial_witness.SaveRAM").write_bytes(baseline)
    proof["witness_snapshots"] = {"a": {"path": "initial_witness.SaveRAM", "sha256": hashlib.sha256(baseline).hexdigest()}}
    changed = bytearray(baseline)
    changed[offset] ^= 1
    (tmp_path / "same_save.SaveRAM").write_bytes(changed)
    digest = hashlib.sha256(changed).hexdigest()
    proof["staged_saves"]["same_save"]["sha256"] = digest
    text["a_same_save"] = _edit_header_field("fixture_sha256", digest)(text["a_same_save"])
    # Receipt duplicates the seed fingerprint; update it too, as a real runner would.
    text["a_same_save"] = text["a_same_save"].replace(hashlib.sha256(baseline).hexdigest(), digest)
    if title != "crystal":
        lines = text["a_wrong_save"].splitlines()
        head = json.loads(lines[0].split(" ", 1)[1])
        lines = ["RECEIPT " + json.dumps({**json.loads(line.split(" ", 1)[1]),
                                       "fixture_sha256": head["fixture_sha256"]}) if line.startswith("RECEIPT ") else line
                 for line in lines]
        text["a_wrong_save"] = "\n".join(lines)
    return proof, axes, lock, text


@pytest.mark.parametrize("title,offset", [("crystal", 0), ("crystal", 0x5ff), ("gold", 0),
                                         ("gold", 0x1800), ("gold", 0x1fff)])
def test_reconnect_matrix_allows_only_authenticated_native_scratch(tmp_path, title, offset):
    proof, axes, lock, text = _scratch_reconnect_cell(tmp_path, offset, title=title)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect") == []


def test_reconnect_matrix_accepts_authenticated_raw_cartram_snapshot(tmp_path):
    proof, axes, lock, text = _scratch_reconnect_cell(tmp_path, 0)
    snapshot = tmp_path / "initial_witness.SaveRAM"
    snapshot.write_bytes(snapshot.read_bytes()[:32768])
    proof["witness_snapshots"]["a"]["sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect") == []


def test_reconnect_matrix_rejects_explicit_bad_snapshot_even_with_unchanged_seed(tmp_path):
    proof, axes, lock, text = _reconnect_cell(tmp_path)
    proof["witness_snapshots"] = {"a": {"path": "same_save.SaveRAM", "sha256": "0" * 64}}
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect")


def test_reconnect_matrix_fails_closed_when_scratch_authority_refuses(tmp_path, monkeypatch):
    from tools import gen2_duo_oracles

    proof, axes, lock, text = _scratch_reconnect_cell(tmp_path, 0)

    def refuse(_raw, _layout):
        raise RuntimeError("native sScratch geometry differs from audited source")

    monkeypatch.setattr(gen2_duo_oracles, "normalized_gameplay_cartram", refuse)
    errors = _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect")
    assert len(errors) == 1 and "geometry differs" in errors[0]


@pytest.mark.parametrize("mutation", ["absent_snapshot", "wrong_snapshot_pin", "forged_snapshot", "short_snapshot",
                                     "live_stage_pin", "wrong_fixture_bytes", "crystal_window", "after_scratch", "next_bank"])
def test_reconnect_matrix_scratch_cannot_hide_unbound_or_gameplay_changes(tmp_path, mutation):
    offset = {"crystal_window": 0x1800, "after_scratch": 0x600, "next_bank": 0x2000}.get(mutation, 0)
    proof, axes, lock, text = _scratch_reconnect_cell(tmp_path, offset)
    if mutation == "absent_snapshot":
        del proof["witness_snapshots"]
    elif mutation == "wrong_snapshot_pin":
        proof["witness_snapshots"]["a"]["sha256"] = "0" * 64
    elif mutation in ("forged_snapshot", "short_snapshot"):
        raw = (tmp_path / "same_save.SaveRAM").read_bytes()
        if mutation == "short_snapshot":
            raw = raw[:32768]
        (tmp_path / "initial_witness.SaveRAM").write_bytes(raw)
        proof["witness_snapshots"]["a"]["sha256"] = hashlib.sha256(raw).hexdigest()
    elif mutation == "live_stage_pin":
        proof["staged_saves"]["same_save"]["sha256"] = "0" * 64
    elif mutation == "wrong_fixture_bytes":
        wrong = bytearray((tmp_path / "wrong_save.SaveRAM").read_bytes())
        wrong[0] ^= 1
        (tmp_path / "wrong_save.SaveRAM").write_bytes(wrong)
        proof["staged_saves"]["wrong_save"]["sha256"] = hashlib.sha256(wrong).hexdigest()
        text["a_wrong_save"] = _edit_header_field("fixture_sha256", hashlib.sha256(wrong).hexdigest())(text["a_wrong_save"])
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect")


@pytest.mark.parametrize("mutation", ["missing_phase", "missing_stage", "stage_pin", "stage_bytes",
    "wrong_fixture", "header_hash", "header_title", "initial_result", "initial_save", "b_result",
    "relaunch_result", "relaunch_save", "phase", "linked", "key", "hud", "b_repeat",
    "force_faint", "pydec_scenario", "pydec_status"])
def test_reconnect_matrix_refuses_partial_or_rebound_proof(tmp_path, mutation):
    proof, axes, lock, text = _reconnect_cell(tmp_path)
    if mutation == "missing_phase":
        del text["a_same_save"]
        del proof["receipts"]["a_same_save"]
    elif mutation == "missing_stage":
        del proof["staged_saves"]["same_save"]
    elif mutation == "stage_pin":
        proof["staged_saves"]["same_save"]["sha256"] = "0" * 64
    elif mutation == "stage_bytes":
        (tmp_path / "same_save.SaveRAM").write_bytes(b"changed")
    elif mutation == "wrong_fixture":
        proof["staged_saves"]["wrong_save"]["case"] = "crystal_battle"
    elif mutation == "header_hash":
        text["a_same_save"] = _edit_header_field("fixture_sha256", "0" * 64)(text["a_same_save"])
    elif mutation == "header_title":
        text["a_same_save"] = _edit_header_field("title", "gold")(text["a_same_save"])
    elif mutation == "initial_result":
        text["a"] += "RESULT: PASS\n"
    elif mutation in ("initial_save", "b_result", "relaunch_result", "hud"):
        side, tag = {"initial_save": ("a", "SAVE_WITNESS"), "b_result": ("b", "RESULT:"),
                     "relaunch_result": ("a_same_save", "RESULT:"), "hud": ("a_wrong_save", "WRONG_SAVE_HUD")}[mutation]
        text[side] = "\n".join(line for line in text[side].splitlines() if not line.startswith(tag + " "))
    elif mutation == "relaunch_save":
        text["a_same_save"] += "SAVE_WITNESS {}\n"
    elif mutation in ("phase", "linked", "key"):
        old, new = {"phase": ('"phase": "same_save"', '"phase": "wrong_save"'),
                    "linked": ('"linked": true', '"linked": false'),
                    "key": ('"expected_key": "1234:5678:00"', '"expected_key": "bad"')}[mutation]
        text["a_same_save"] = text["a_same_save"].replace(old, new)
    elif mutation == "b_repeat":
        text["b"] += "HELLO_AGAIN {}\n"
    elif mutation == "force_faint":
        text["a_wrong_save"] += "RX force_faint key=x\n"
    else:
        key, value = ("scenario", "link") if mutation == "pydec_scenario" else ("status", "dead")
        text["pydec"] = _edit_pydec_token(key, value)(text["pydec"])
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_reconnect")


def _soft_reset_cell(tmp_path):
    doc = _green_tree(tmp_path)
    row = _row(doc, "duo.crystal.crystal")
    proof, axes = row["proofs"][0], row["axes"]
    lock = json.loads((tmp_path / "data/gen2_sources.lock.json").read_text())["outputs"]
    text = {}
    for side in ("a", "b"):
        case = axes["fixtures"][side]
        head = {"player": side, "scenario": "gen2_soft_reset", "title": "crystal", "case": case,
                "rom_sha1": lock["pokecrystal"]["sha1"], "attempt": 1,
                "fixture_sha256": gate._fixture_sha256(tmp_path, case)}
        client = {"production_admitted": True}
        hello = {"frame": 100, "ot_id": 46401 if side == "a" else 44068}
        save = {"frame": 1000, "save_completed_frame": 999, "flushed_matches": True,
                "cartram_bytes": 32768, "cartram_sha256": "a" * 64, "gate_saves": 1, "client_saves": 1}
        records = [("DUO_GEN2", head), ("CLIENT", client), ("BOOTED", {"frame": 99}), ("HELLO", hello)]
        detail = {}
        if side == "a":
            rows = {
                "HELLO_AT_CHECKPOINT": {"frame": 110, "ot_id": 46401, "hellos": 1, "writes_enabled": True},
                "CHORD_GATE": {"frame": 111}, "CHORD": {"frame": 112, "frames": 4},
                "RESET_SEEN": {"frame": 145, "delta": 33}, "HELLO_CLEARED": {"frame": 150, "delta": 5},
                "WRITES_PAUSED": {"frame": 400, "delta": 255},
                "HELLO_AGAIN": {"frame": 600, "ot_id": 46401, "n": 2},
                "REBOOTED": {"frame": 601}, "WRITES_RESUMED": {"frame": 602, "delta": 457},
                "REHELLO": {"frame": 603, "ot_id": 46401, "hellos": 2},
                "NO_WRITES_IN_WINDOW": {"writes": 0},
            }
            records.extend(rows.items())
            detail = {"reset": rows["RESET_SEEN"], "paused": rows["WRITES_PAUSED"], "rehello": rows["REHELLO"]}
        else:
            idle = {"frame": 700, "hellos": 1}
            records.append(("IDLE_PARTNER", idle))
            detail = {"idle": idle}
        receipt = {**head, "schema": "gen2-duo-soft-reset-v1", "client": client,
                   "hello": hello, "save": save, **detail}
        records.extend([("SAVE_WITNESS", save), ("RECEIPT", receipt)])
        text[side] = "\n".join(tag + " " + json.dumps(value) for tag, value in records) + "\nRESULT: PASS\n"
    text["pydec"] = ("PYDEC: PASS scenario=gen2_soft_reset a=reset b=idle area=none "
                     "titles=crystal/crystal status=unchanged\n")
    return proof, axes, lock, text


def test_soft_reset_matrix_requires_chronological_reset_receipts(tmp_path):
    proof, axes, lock, text = _soft_reset_cell(tmp_path)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_soft_reset") == []


def test_soft_reset_matrix_allows_production_hello_before_arrival_marker(tmp_path):
    proof, axes, lock, text = _soft_reset_cell(tmp_path)
    for side in ("a", "b"):
        lines = text[side].splitlines()
        booted = next(i for i, line in enumerate(lines) if line.startswith("BOOTED "))
        hello = next(i for i, line in enumerate(lines) if line.startswith("HELLO "))
        lines[booted], lines[hello] = lines[hello], lines[booted]
        text[side] = "\n".join(lines)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_soft_reset") == []


@pytest.mark.parametrize("mutation", ["pause_missing", "no_write_missing", "writes", "reset_delta", "delta_lie",
    "pause_early", "wrong_ot", "three_hellos", "idle_repeat", "idle_reset", "save_early", "save_missing",
    "fixture_hash", "fake_engine", "receipt_detail", "receipt_missing", "pydec_status", "pydec_side",
    "pydec_scenario", "order", "no_client"])
def test_soft_reset_matrix_refuses_weak_receipts(tmp_path, mutation):
    proof, axes, lock, text = _soft_reset_cell(tmp_path)
    if mutation in ("pause_missing", "no_write_missing", "save_missing", "receipt_missing"):
        tag = {"pause_missing": "WRITES_PAUSED", "no_write_missing": "NO_WRITES_IN_WINDOW",
               "save_missing": "SAVE_WITNESS", "receipt_missing": "RECEIPT"}[mutation]
        text["a"] = "\n".join(line for line in text["a"].splitlines() if not line.startswith(tag + " "))
    elif mutation in ("writes", "reset_delta", "delta_lie", "pause_early", "wrong_ot", "three_hellos", "save_early", "no_client"):
        old, new = {"writes": ('"writes": 0', '"writes": 1'),
                    "reset_delta": ('"delta": 33', '"delta": 1'),
                    "delta_lie": ('"frame": 145', '"frame": 146'),
                    "pause_early": ('"delta": 255', '"delta": 60'),
                    "wrong_ot": ('"ot_id": 46401, "n": 2', '"ot_id": 44068, "n": 2'),
                    "three_hellos": ('"hellos": 2', '"hellos": 3'),
                    "save_early": ('"save_completed_frame": 999', '"save_completed_frame": 500'),
                    "no_client": ('"production_admitted": true', '"production_admitted": false')}[mutation]
        text["a"] = text["a"].replace(old, new)
    elif mutation in ("idle_repeat", "idle_reset", "fake_engine"):
        side, tag = {"idle_repeat": ("b", "HELLO_AGAIN"), "idle_reset": ("b", "CHORD"),
                     "fake_engine": ("a", "ENGINE_CAPTURE")}[mutation]
        text[side] += tag + " {}\n"
    elif mutation == "fixture_hash":
        text["a"] = _edit_header_field("fixture_sha256", "0" * 64)(text["a"])
    elif mutation == "receipt_detail":
        text["a"] = text["a"].replace('"paused": {"frame": 400', '"paused": {"frame": 401')
    elif mutation == "order":
        lines = text["a"].splitlines()
        x, y = [next(i for i, line in enumerate(lines) if line.startswith(tag + " "))
                for tag in ("CHORD_GATE", "CHORD")]
        lines[x], lines[y] = lines[y], lines[x]
        text["a"] = "\n".join(lines)
    else:
        key, value = {"pydec_status": ("status", "alive"), "pydec_side": ("a", "idle"),
                      "pydec_scenario": ("scenario", "link")}[mutation]
        text["pydec"] = _edit_pydec_token(key, value)(text["pydec"])
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_soft_reset")


def _clause_cell(tmp_path, kind):
    proof, axes, lock, _ = _soft_reset_cell(tmp_path)
    scenario = f"gen2_{kind}_clause"
    keys, text = {"a": "1234:5678:10", "b": "2234:5678:13"}, {}
    for side in ("a", "b"):
        species = 16 if side == "a" else 19
        case = axes["fixtures"][side]
        head = {"player": side, "scenario": scenario, "title": "crystal", "case": case, "attempt": 1,
                "rom_sha1": lock["pokecrystal"]["sha1"], "fixture_sha256": gate._fixture_sha256(tmp_path, case)}
        cap = {"frame": 100, "key": keys[side], "species_id": species, "area_id": "route_29"}
        save = {"frame": 300, "save_completed_frame": 299, "gate_saves": 2, "client_saves": 2,
                "flushed_matches": True, "cartram_bytes": 32768, "cartram_sha256": "a" * 64}
        rows = [("DUO_GEN2", head), ("CLIENT", {"production_admitted": True}), ("ENGINE_CAPTURE", cap),
                ("CAPTURE_SENT", {"frame": 101, "key": keys[side]})]
        receipt = {**head, "schema": f"gen2-duo-{kind}-clause-v1", "key": keys[side],
                   "species_id": species, "capture": cap, "save": save}
        if kind == "species":
            if side == "a":
                rows.append(("PENDING_CAPTURE", cap))
                receipt.update(role="pending", path="pending", rerolls=0)
            else:
                encounters = [("A_PENDING", {"frame": 50, "species_id": 16}),
                              ("ENCOUNTER", {"frame": 60, "n": 1, "species_id": 16, "dupe": True}),
                              ("RX_TEXT", {"cmd": "gui_prompt", "text": "Dupes clause: Pidgey -- reroll!"}),
                              ("REROLL", {"frame": 70, "n": 1, "species_id": 16,
                                          "prompt": "Dupes clause: Pidgey -- reroll!"}),
                              ("ENCOUNTER", {"frame": 90, "n": 2, "species_id": 19, "dupe": False})]
                rows[2:2] = encounters
                receipt.update(role="reroller", path="reroll_observed", rerolls=1, dupe_species=16)
            rows.append(("LINKED", {"frame": 200, "text": "A and B linked!"}))
        else:
            verdict = "partner_rejected" if side == "a" else "rejected"
            rows.append(("CLAUSE_CAPTURE", cap))
            rows.append(("CLAUSE_VERDICT", {"frame": 200, "verdict": verdict}))
            receipt.update(clause=kind, path="clause_observed", verdict=verdict)
            if side == "b":
                rows.extend([("PARTY_HP_WRITE", {"frame": 201, "key": keys[side], "ok": True}),
                             ("MEMORIAL_ACK", {"frame": 202, "key": keys[side], "event": "memorialize_failed"}),
                             ("REJECTED_MON", {"frame": 203, "key": keys[side], "ending": "dead", "hp": 0,
                                               "in_party": True})])
                receipt["ending"] = "dead"
        rows.extend([("SAVE_WITNESS", save), ("RECEIPT", receipt)])
        text[side] = "\n".join(tag + " " + json.dumps(value) for tag, value in rows) + "\nRESULT: PASS\n"
    facts = "status=alive clause=species rerolls=1" if kind == "species" else (
        f"status=clause_observed clause={kind} rejected=b ending=dead")
    text["pydec"] = (f"PYDEC: PASS scenario={scenario} a={keys['a']} b={keys['b']} "
                     f"area=route_29 titles=crystal/crystal {facts}\n")
    return proof, axes, lock, text


@pytest.mark.parametrize("kind", ["species", "type", "gender"])
def test_clause_matrix_accepts_observed_branch(tmp_path, kind):
    proof, axes, lock, text = _clause_cell(tmp_path, kind)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, f"gen2_{kind}_clause") == []


@pytest.mark.parametrize("prompt_position", ["intro", "second_intro", "before_pending", "previous_battle"])
def test_species_matrix_binds_intro_prompt_to_its_own_reroll_window(tmp_path, prompt_position):
    proof, axes, lock, text = _clause_cell(tmp_path, "species")
    lines = text["b"].splitlines()
    first_encounter = next(i for i, line in enumerate(lines) if line.startswith("ENCOUNTER "))
    prompt = next(i for i, line in enumerate(lines) if line.startswith("RX_TEXT "))
    # The server can send its reroll prompt during the intro, before BattleMenu prints ENCOUNTER.
    lines.insert(first_encounter, lines.pop(prompt))
    if prompt_position == "before_pending":
        ap = next(i for i, line in enumerate(lines) if line.startswith("A_PENDING "))
        prompt = next(i for i, line in enumerate(lines) if line.startswith("RX_TEXT "))
        lines.insert(ap, lines.pop(prompt))
    elif prompt_position in ("previous_battle", "second_intro"):
        first_reroll = next(i for i, line in enumerate(lines) if line.startswith("REROLL "))
        final_encounter = next(i for i in range(first_reroll + 1, len(lines)) if lines[i].startswith("ENCOUNTER "))
        final = json.loads(lines[final_encounter].split(" ", 1)[1])
        final["n"] = 3
        lines[final_encounter] = "ENCOUNTER " + json.dumps(final)
        lines[final_encounter:final_encounter] = [
            'ENCOUNTER {"frame":80,"n":2,"species_id":16,"dupe":true}',
            'REROLL {"frame":85,"n":2,"species_id":16,"prompt":"Dupes clause: Pidgey -- reroll!"}',
        ]
        if prompt_position == "second_intro":
            lines.insert(final_encounter, 'RX_TEXT {"cmd":"gui_prompt","text":"Dupes clause: Pidgey -- reroll!"}')
        # Re-pin every claim: only the missing distinct prompt in battle two can reject this proof.
        lines = [line.replace('"rerolls": 1', '"rerolls": 2') for line in lines]
        text["pydec"] = _edit_pydec_token("rerolls", "2")(text["pydec"])
    text["b"] = "\n".join(lines)
    errors = _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_species_clause")
    if prompt_position in ("intro", "second_intro"):
        assert errors == []
    else:
        assert any("reroll lacks observed server prompt" in error for error in errors), errors


@pytest.mark.parametrize("kind", ["type", "gender"])
def test_clause_matrix_accepts_proven_memorial_ending(tmp_path, kind):
    proof, axes, lock, text = _clause_cell(tmp_path, kind)
    text["b"] = text["b"].replace('"event": "memorialize_failed"', '"event": "memorialize_done", "box": 13')
    text["b"] = text["b"].replace('"ending": "dead"', '"ending": "memorial", "box": 13').replace(
        '"in_party": true', '"in_party": false')
    text["pydec"] = _edit_pydec_token("ending", "memorial")(text["pydec"])
    text["b"] = _add_memorial_preimage(text["b"], "2234:5678:13")
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, f"gen2_{kind}_clause") == []


def _add_memorial_preimage(text, key):
    dv, ot, species = (int(part, 16) for part in key.split(":"))
    raw = bytearray(48)
    raw[0], raw[31] = species, 2
    raw[6:8], raw[21:23] = ot.to_bytes(2, "big"), dv.to_bytes(2, "big")
    pre = {"frame": 201, "key": key, "slot": 1, "raw_hex": raw.hex(), "ot_raw_hex": "50" * 11,
           "nickname_raw_hex": "50" * 11, "species_marker": species}
    return text.replace("MEMORIAL_ACK ", "MEMORIAL_PREIMAGE " + json.dumps(pre) + "\nMEMORIAL_ACK ")


def _active_faint_cell(tmp_path, pair="duo.crystal.crystal"):
    doc = _green_tree(tmp_path)
    row = _row(doc, pair)
    proof, axes = row["proofs"][0], row["axes"]
    lock = json.loads((REPO / "data/gen2_sources.lock.json").read_text())["outputs"]
    keys, text = {"a": "1234:5678:10", "b": "2234:5678:13"}, {}
    for side, title in (("a", axes["initiator"]), ("b", axes["partner"])):
        profile = json.loads((REPO / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        hold = json.loads((REPO / f"data/games/gen2_{title}/write_checkpoint.json").read_text())["titles"][title]["battle_hold"]
        head = {"player": side, "scenario": "gen2_faint_active", "title": title, "case": axes["fixtures"][side],
                "attempt": 1, "rom_sha1": lock[f"poke{title}"]["sha1"],
                "fixture_sha256": gate._fixture_sha256(tmp_path, axes["fixtures"][side])}
        cap = {"frame": 100, "key": keys[side], "slot": 1, "species_id": 16 if side == "a" else 19,
               "area_id": "route_29"}
        link = {"frame": 110, "key": keys[side], "cartram_bytes": 32768, "saveram_bytes": 32790,
                "cartram_sha256": "b" * 64, "gate_saves": 1, "client_saves": 1}
        save = {"frame": 300, "save_completed_frame": 299, "gate_saves": 2, "client_saves": 2,
                "cartram_bytes": 32768, "flushed_matches": True, "cartram_sha256": "c" * 64}
        rows = [("DUO_GEN2", head), ("CLIENT", {"production_admitted": True, "registered_sites": ["battle_faint"]}),
                ("ENGINE_CAPTURE", cap), ("LINK_SAVE", link)]
        receipt = {**head, "schema": "gen2-duo-faint-active-v1", "capture": cap, "key": keys[side],
                   "save": save, "link_save": link}
        if side == "a":
            go = {"frame": 120}
            faint = {"frame": 190, "key": keys[side], "site_id": "battle_faint", "cause": "battle", "slot": 1}
            rows.extend([("B_ACTIVE", go), ("ENGINE_FAINT", faint), ("FAINT_SENT", faint)])
            receipt["b_active"] = go
            receipt.update(faint=faint, faint_sent=faint)
        else:
            active = {"frame": 120, "key": keys[side], "slot": 1, "cur_battle_mon": 1,
                      "battle_mon_species": 19, "battle_mode": 1, "battle_type": 0, "link_mode": 0}
            address = profile["ram"]["wPartyMons"] + 48
            targets = hold["write"]["targets"]
            spans = [(targets["wBattleMonHP"]["address"], 2), (address + 32, 1), (address + 34, 2),
                     (targets["wBattlePlayerAction"]["address"], 1)]
            log = [{"domain": "System Bus", "addr": addr, "n": n, "batch_index": i, "batch_size": 4,
                    "status": "written", "completed": n, "attempted": n, "why": "battle_hold", "title": title,
                    "artifact": profile["artifact"], "rom_sha1": profile["rom_sha1"],
                    "site": "lua/gen2/entry.lua production", "evidence": "U2 PHYSICAL receipt"}
                   for i, (addr, n) in enumerate(spans, 1)]
            write = {"frame": 200, "seq": 1, "key": keys[side], "slot": 1, "active_slot": 1,
                     "kind": "battle_faint", "ok": True, "pc": hold["execution_before"]["pc"],
                     "hrom_bank": hold["execution_before"]["bank"], "battle_hp_before_hex": "000A",
                     "battle_hp_after_hex": "0000", "hp_before_hex": "000A", "hp_after_hex": "0000",
                     "status_after_hex": "00", "action_before_hex": "00", "action_after_hex": "01", "log": log}
            trace = {"seq": 2, "what": "faint", "frame": 200}
            replaced = {"frame": 220, "active_slot": 0, "hp": 20}
            rows.extend([("LINKED_ACTIVE", active), ("RX", "force_faint key=" + keys[side]),
                         ("BATTLE_HOLD_WRITE", write), ("BATTLE_TRACE", trace), ("NEXT_MON", {"frame": 210}),
                         ("REPLACED", replaced), ("LINKED_HP_STATUS", "0000 00")])
            receipt.update(linked_active=active, force_faint_key=keys[side],
                battle_write={key: write[key] for key in ("frame", "seq", "slot", "pc", "hrom_bank", "battle_hp_before_hex", "action_after_hex")},
                native_faint=trace, replaced=replaced)
        ack = {"frame": 250, "key": keys[side], "event": "memorialize_done", "box": 13}
        if side == "b":
            receipt["memorial"] = {"preimage_frame": 240, "ack": ack}
        rows.extend([("MEMORIAL_ACK", ack), ("SAVE_WITNESS", save), ("RECEIPT", receipt)])
        body = "\n".join(tag + " " + (value if isinstance(value, str) else json.dumps(value)) for tag, value in rows)
        body = _add_memorial_preimage(body, keys[side]).replace('"frame": 201', '"frame": 240')
        text[side] = body + "\nRESULT: PASS\n"
    text["pydec"] = (f"PYDEC: PASS scenario=gen2_faint_active a={keys['a']} b={keys['b']} area=route_29 "
                     f"titles={axes['initiator']}/{axes['partner']} status=memorial death=active\n")
    return proof, axes, lock, text


@pytest.mark.parametrize("pair", ["duo.crystal.crystal", "duo.gold.silver", "duo.crystal.gold"])
def test_active_faint_matrix_accepts_the_pack_bound_active_write(tmp_path, pair):
    proof, axes, lock, text = _active_faint_cell(tmp_path, pair)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_faint_active") == []


def test_active_faint_is_required_for_each_existing_duo_pairing():
    doc = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    expected = {"duo.crystal.crystal": "gen2_new", "duo.gold.silver": "gen2_gold_silver",
                "duo.crystal.gold": "gen2_crystal_gold"}
    for rid, game in expected.items():
        axes = _row(doc, rid)["axes"]
        assert axes["pairing"] == game
        assert axes["scenarios"].count("gen2_faint_active") == 1


def test_active_faint_matrix_allows_readback_after_memorial_ack(tmp_path):
    proof, axes, lock, text = _active_faint_cell(tmp_path)
    lines = text["b"].splitlines()
    readback = next(line for line in lines if line.startswith("LINKED_HP_STATUS "))
    lines.remove(readback)
    at = next(i for i, line in enumerate(lines) if line.startswith("MEMORIAL_ACK "))
    lines.insert(at + 1, readback)
    text["b"] = "\n".join(lines)
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_faint_active") == []


@pytest.mark.parametrize("mutation", ["schema", "bench_only", "pc", "bank", "span_addr", "span_count", "span_order",
    "span_status", "span_title", "nonzero_hp", "wrong_action", "wrong_slot", "no_force", "early_force", "enemy_first",
    "faint_next_frame", "lost", "trace_seq", "echo", "replacement_dead", "replacement_same", "no_readback",
    "a_go_early", "a_go_missing", "a_no_send", "a_other_cause", "a_written", "save_early", "pydec_bench", "pydec_pass", "repeat_mutates"])
def test_active_faint_matrix_refuses_bench_or_incomplete_active_evidence(tmp_path, mutation):
    proof, axes, lock, text = _active_faint_cell(tmp_path)
    lines = text["b"].splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("BATTLE_HOLD_WRITE "))
    write = json.loads(lines[at].split(" ", 1)[1])
    if mutation == "pc":
        write["pc"] += 1
    elif mutation == "bank":
        write["hrom_bank"] += 1
    elif mutation == "span_addr":
        write["log"][0]["addr"] += 1
    elif mutation == "span_count":
        write["log"].pop()
    elif mutation == "span_order":
        write["log"].reverse()
    elif mutation == "span_status":
        write["log"][0]["status"] = "error"
    elif mutation == "span_title":
        write["log"][0]["title"] = "gold"
    elif mutation == "nonzero_hp":
        write["hp_after_hex"] = "0001"
    elif mutation == "wrong_action":
        write["action_after_hex"] = "00"
    elif mutation == "wrong_slot":
        write["active_slot"] = 0
    lines[at] = "BATTLE_HOLD_WRITE " + json.dumps(write)
    if mutation == "schema":
        lines = [line.replace("gen2-duo-faint-active-v1", "gen2-duo-faint-v1") for line in lines]
    elif mutation == "bench_only":
        lines[at] = 'PARTY_HP_WRITE {"ok":true,"before_party_hex":"00","after_party_hex":"00"}'
    elif mutation == "no_force":
        lines = [line for line in lines if not line.startswith("RX force_faint ")]
    elif mutation == "early_force":
        i = next(i for i, line in enumerate(lines) if line.startswith("LINKED_ACTIVE "))
        lines[i], lines[i + 1] = lines[i + 1], lines[i]
    elif mutation in ("enemy_first", "faint_next_frame", "lost", "trace_seq"):
        i = next(i for i, line in enumerate(lines) if line.startswith("BATTLE_TRACE "))
        trace = json.loads(lines[i].split(" ", 1)[1])
        if mutation == "enemy_first":
            trace["what"] = "enemy_turn"
        elif mutation == "lost":
            trace["what"] = "lost"
        elif mutation == "trace_seq":
            trace["seq"] = 1
        else:
            trace["frame"] = 201
        lines[i] = "BATTLE_TRACE " + json.dumps(trace)
    elif mutation == "echo":
        lines.append('FAINT_SENT {"key":"2234:5678:13"}')
    elif mutation in ("replacement_dead", "replacement_same"):
        old, new = ('"hp": 20', '"hp": 0') if mutation == "replacement_dead" else ('"active_slot": 0', '"active_slot": 1')
        lines = [line.replace(old, new)
                 if line.startswith("REPLACED ") else line for line in lines]
    elif mutation == "no_readback":
        lines = [line for line in lines if not line.startswith("LINKED_HP_STATUS ")]
    elif mutation == "save_early":
        lines = [line.replace('"save_completed_frame": 299', '"save_completed_frame": 199') for line in lines]
    elif mutation == "repeat_mutates":
        lines.append('PARTY_HP_WRITE {"ok":true,"before_party_hex":"00","after_party_hex":"01"}')
    text["b"] = "\n".join(lines)
    if mutation == "a_go_missing":
        text["a"] = "\n".join(line for line in text["a"].splitlines() if not line.startswith("B_ACTIVE "))
    elif mutation == "a_no_send":
        text["a"] = "\n".join(line for line in text["a"].splitlines() if not line.startswith("FAINT_SENT "))
    elif mutation == "a_other_cause":
        text["a"] = text["a"].replace('"cause": "battle"', '"cause": "poison"')
    elif mutation == "a_written":
        text["a"] += '\nPARTY_HP_WRITE {"ok":true}\n'
    elif mutation == "a_go_early":
        text["a"] = text["a"].replace('"frame": 120', '"frame": 99')
    elif mutation == "pydec_bench":
        text["pydec"] = text["pydec"].replace("death=active", "death=bench")
    elif mutation == "pydec_pass":
        text["pydec"] = "PYDEC: PASS\n"
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_faint_active")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_memorial_preimage_uses_each_titles_party_codec(title):
    rows = [("DUO_GEN2", {"title": title}), ("ENGINE_CAPTURE", {"key": "2234:5678:13", "species_id": 19}),
            ("MEMORIAL_ACK", {"frame": 201, "key": "2234:5678:13", "event": "memorialize_done", "box": 13}),
            ("SAVE_WITNESS", {"save_completed_frame": 202})]
    text = "\n".join(tag + " " + json.dumps(value) for tag, value in rows)
    text = _add_memorial_preimage(text, "2234:5678:13")
    assert gate._memorial_receipt_errors(text.splitlines(), "a") == []


@pytest.mark.parametrize("pair", ["duo.crystal.crystal", "duo.gold.silver", "duo.crystal.gold"])
def test_old_memorial_faint_receipts_require_real_preimage(tmp_path, pair):
    # Rebuild the historical NACK-only shape; fresh physical receipts must never remove this control.
    doc = _green_tree(tmp_path)
    row = _row(doc, pair)
    proof = row["proofs"][0]
    text = {side: (tmp_path / entry["path"]).read_text(encoding="utf-8")
            for side, entry in proof["receipts"].items()}
    for side in ("a", "b"):
        text[side] = text[side].replace('"scenario": "link"', '"scenario": "gen2_faint"')
        text[side] += 'MEMORIAL_ACK {"event":"memorialize_failed","reason":"not implemented"}\n'
    text["pydec"] = _edit_pydec_token("status", "memorial")(text["pydec"])
    lock = json.loads((REPO / "data/gen2_sources.lock.json").read_text(encoding="utf-8"))["outputs"]
    errors = _check_admission_cell(tmp_path, proof, row["axes"], lock, text, "gen2_faint")
    assert any("a memorial" in error and "MEMORIAL_PREIMAGE" in error for error in errors), errors
    assert any("b memorial" in error and "MEMORIAL_PREIMAGE" in error for error in errors), errors


@pytest.mark.parametrize("mutation", ["absent", "positive_hp", "box_record", "wrong_key", "wrong_species",
    "ot_length", "nickname_length", "wrong_box", "nack", "duplicate", "duplicate_ack", "late", "frame_lie",
    "slot", "late_write", "save_same_frame"])
def test_clause_memorial_requires_actual_party_preimage(tmp_path, mutation):
    proof, axes, lock, text = _clause_cell(tmp_path, "type")
    text["b"] = text["b"].replace('"event": "memorialize_failed"', '"event": "memorialize_done", "box": 13')
    text["b"] = text["b"].replace('"ending": "dead"', '"ending": "memorial", "box": 13').replace(
        '"in_party": true', '"in_party": false')
    text["pydec"] = _edit_pydec_token("ending", "memorial")(text["pydec"])
    text["b"] = _add_memorial_preimage(text["b"], "2234:5678:13")
    lines = text["b"].splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("MEMORIAL_PREIMAGE "))
    pre = json.loads(lines[at].split(" ", 1)[1])
    if mutation == "positive_hp":
        raw = bytearray.fromhex(pre["raw_hex"])
        raw[35] = 1
        pre["raw_hex"] = raw.hex()
    elif mutation == "box_record":
        pre["raw_hex"] = pre["raw_hex"][:64]
    elif mutation == "wrong_key":
        pre["key"] = "1234:5678:10"
    elif mutation == "wrong_species":
        pre["species_marker"] = 16
    elif mutation in ("ot_length", "nickname_length"):
        pre["ot_raw_hex" if mutation == "ot_length" else "nickname_raw_hex"] = "50"
    elif mutation == "frame_lie":
        pre["frame"] = 204
    elif mutation == "slot":
        pre["slot"] = 6
    lines[at] = "MEMORIAL_PREIMAGE " + json.dumps(pre)
    if mutation == "absent":
        del lines[at]
    elif mutation == "duplicate":
        lines.insert(at, lines[at])
    elif mutation == "duplicate_ack":
        lines.insert(at + 1, lines[at + 1])
    elif mutation == "late":
        lines[at], lines[at + 1] = lines[at + 1], lines[at]
    elif mutation == "late_write":
        index = next(i for i, line in enumerate(lines) if line.startswith("PARTY_HP_WRITE "))
        lines.insert(at + 1, lines.pop(index))
    text["b"] = "\n".join(lines)
    if mutation == "wrong_box":
        text["b"] = text["b"].replace('"box": 13', '"box": 12')
    elif mutation == "nack":
        text["b"] = text["b"].replace('"memorialize_done"', '"memorialize_failed"')
    elif mutation == "save_same_frame":
        text["b"] = text["b"].replace('"save_completed_frame": 299', '"save_completed_frame": 202')
    errors = _check_admission_cell(tmp_path, proof, axes, lock, text, "gen2_type_clause")
    assert any("memorial" in error for error in errors), errors


@pytest.mark.parametrize("kind,mutation", [(kind, mutation) for kind in ("species", "type", "gender")
    for mutation in ("unobserved", "first_save", "early_save", "receipt_missing", "wrong_fact", "header_hash")]
    + [("species", "no_reroll"), ("species", "no_prompt"), ("species", "same_species"),
       ("type", "no_write"), ("type", "wrong_ending"), ("gender", "wrong_rejected"), ("gender", "two_rejected")])
def test_clause_matrix_refuses_unobserved_or_rebound_receipts(tmp_path, kind, mutation):
    proof, axes, lock, text = _clause_cell(tmp_path, kind)
    if mutation == "unobserved":
        text["b"] = text["b"].replace('"reroll_observed"', '"reroll_unobserved"').replace(
            '"clause_observed"', '"clause_unobserved"').replace('"verdict": "rejected"', '"verdict": "linked"')
    elif mutation == "first_save":
        text["b"] = text["b"].replace('"gate_saves": 2', '"gate_saves": 1')
    elif mutation == "early_save":
        text["b"] = text["b"].replace('"save_completed_frame": 299', '"save_completed_frame": 101')
    elif mutation in ("receipt_missing", "no_reroll", "no_prompt", "no_write"):
        tag = {"receipt_missing": "RECEIPT", "no_reroll": "REROLL", "no_prompt": "RX_TEXT",
               "no_write": "PARTY_HP_WRITE"}[mutation]
        text["b"] = "\n".join(line for line in text["b"].splitlines() if not line.startswith(tag + " "))
    elif mutation == "wrong_fact":
        text["pydec"] = _edit_pydec_token("clause", "wrong")(text["pydec"])
    elif mutation == "header_hash":
        text["b"] = _edit_header_field("fixture_sha256", "0" * 64)(text["b"])
    elif mutation == "same_species":
        text["b"] = text["b"].replace('"species_id": 19', '"species_id": 16')
    elif mutation == "wrong_ending":
        text["pydec"] = _edit_pydec_token("ending", "memorial")(text["pydec"])
    elif mutation == "wrong_rejected":
        text["pydec"] = _edit_pydec_token("rejected", "a")(text["pydec"])
    elif mutation == "two_rejected":
        text["a"] = text["a"].replace('"partner_rejected"', '"rejected"')
    assert _check_admission_cell(tmp_path, proof, axes, lock, text, f"gen2_{kind}_clause")


def _trade_cell(tmp_path, scenario="gen2_trade_new", pair="duo.crystal.crystal"):
    """A HARNESS_ONLY_OVERLAY trade proof for one cell, bound to the CURRENT published overlay pins."""
    doc = _green_tree(tmp_path)
    axes = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    axes = _row(axes, pair)["axes"]
    return doc, _trade_proof(tmp_path, axes, scenario), axes


def _trade_proof(tmp_path, axes, scenario, tag="trade"):
    (tmp_path / "data/gen2").mkdir(parents=True, exist_ok=True)
    provenance = (REPO / "data/gen2/overlay_provenance.json").read_bytes()
    (tmp_path / "data/gen2/overlay_provenance.json").write_bytes(provenance)
    pins = {row["slink_title"]: row["sha1"] for row in json.loads(provenance)["outputs"].values()}
    titles = {"a": axes["initiator"], "b": axes["partner"]}
    variant = gate.TRADE_VARIANTS[(titles["a"], titles["b"])]
    status = gate.TRADE_END_STATUS[scenario]
    text = {}
    for side in ("a", "b"):
        fixture = axes["trade_fixtures"][side]
        raw = (REPO / "tests/fixtures/gen2" / f"{fixture}.SaveRAM").read_bytes()
        (tmp_path / "tests/fixtures/gen2" / f"{fixture}.SaveRAM").write_bytes(raw)
        receipt = {"schema": "gen2-duo-trade-v1", "case": scenario, "player": side, "title": titles[side],
                   "variant": variant, "outcome": status, "admission_scope": "HARNESS_ONLY_OVERLAY",
                   "rom_sha1": pins[titles[side]], "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                   "harness_exception": "O-31" if scenario in gate.TRADE_PLANTED and side == "a" else None}
        text[side] = "RECEIPT " + json.dumps(receipt) + "\nRESULT: PASS\n"
    text["pydec"] = (f"PYDEC: PASS a=AAAA:1:01 b=BBBB:2:02 area=route_29 titles={titles['a']}/{titles['b']} "
                     f"status={status} scenario={scenario} admission_scope=HARNESS_ONLY_OVERLAY\n")
    proof = {"scenario": scenario, "receipts": {}}
    for side, body in text.items():
        path = tmp_path / "receipts" / f"{tag}_{side}.txt"
        path.write_text(body, encoding="utf-8", newline="\n")
        proof["receipts"][side] = {"path": path.relative_to(tmp_path).as_posix(), "sha256": _lf_sha(path)}
    return proof


@pytest.mark.parametrize("scenario", sorted(gate.TRADE_END_STATUS))
@pytest.mark.parametrize("pair", ["duo.crystal.crystal", "duo.gold.silver", "duo.crystal.gold"])
def test_trade_matrix_accepts_a_bound_overlay_receipt(tmp_path, scenario, pair):
    _doc, proof, axes = _trade_cell(tmp_path, scenario, pair)
    assert gate._receipt_errors(tmp_path, proof, scenario, axes, {}) == []


def _retext(tmp_path, proof, side, old, new):
    path = tmp_path / proof["receipts"][side]["path"]
    body = path.read_text(encoding="utf-8")
    assert old in body
    path.write_text(body.replace(old, new), encoding="utf-8", newline="\n")
    proof["receipts"][side]["sha256"] = _lf_sha(path)


_TRADE_GAPS = {
    "clean_rom_pin": ("a", '"rom_sha1": "', '"rom_sha1": "0'),
    "battle_fixture": ("b", '"fixture_sha256": "', '"fixture_sha256": "0'),
    "wrong_variant": ("a", '"variant": "cc"', '"variant": "gs"'),
    "production_scope": ("b", '"admission_scope": "HARNESS_ONLY_OVERLAY"', '"admission_scope": "PHYSICAL"'),
    "undisclosed_plant": ("a", '"harness_exception": null', '"harness_exception": "O-31"'),
    "other_case": ("a", '"case": "gen2_trade_new"', '"case": "gen2_trade_timeout"'),
    "fail_verdict": ("b", "RESULT: PASS", "RESULT: FAIL"),
    "pydec_scope": ("pydec", "admission_scope=HARNESS_ONLY_OVERLAY", "admission_scope=PHYSICAL"),
    "pydec_status": ("pydec", "status=committed", "status=unchanged"),
}


@pytest.mark.parametrize("gap", sorted(_TRADE_GAPS))
def test_trade_matrix_refuses_unbound_receipts(tmp_path, gap):
    _doc, proof, axes = _trade_cell(tmp_path)
    _retext(tmp_path, proof, *_TRADE_GAPS[gap])
    assert gate._receipt_errors(tmp_path, proof, "gen2_trade_new", axes, {}) != []


def test_trade_matrix_refuses_a_republished_overlay(tmp_path):
    _doc, proof, axes = _trade_cell(tmp_path)
    path = tmp_path / "data/gen2/overlay_provenance.json"
    doc = json.loads(path.read_text())
    doc["outputs"]["pokecrystal"]["sha1"] = "0" * 40
    path.write_text(json.dumps(doc))
    assert gate._receipt_errors(tmp_path, proof, "gen2_trade_new", axes, {}) != []


def test_every_cell_declares_all_trade_cases_with_the_runner_fixtures():
    """Owner O-34: native trades on every release pair, C-G included."""
    import e2e_duo as duo
    doc = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    for row in doc["requirements"]:
        axes = row["axes"]
        assert set(gate.TRADE_END_STATUS) <= set(axes["scenarios"])
        assert axes["trade_fixtures"] == _TRADE_FIXTURES[axes["pairing"]]
        if axes["pairing"] in duo.GEN2_TRADE_FIXTURES:   # the runner re-adds C-G after O-34 in its own card
            assert axes["trade_fixtures"] == duo.GEN2_TRADE_FIXTURES[axes["pairing"]]
    # Every runner case is a release cell; the lane may demand more (refusal rows awaiting a driver).
    assert set(duo.GEN2_TRADE_SCENARIOS) <= set(gate.TRADE_END_STATUS)
    assert "gen2_trade_refuse_unsaved" in gate.TRADE_END_STATUS
    assert "gen2_trade_refuse_contest" not in gate.TRADE_END_STATUS  # MODEL-only (coordinator ruling)


# --- RELEASE-LANES: patch-build, live-gates, live-trade-gates, duo-pairs, release-evidence -----------
# Each lane is RED while its receipts are missing or stale and green only on a valid tree (MODEL
# fixtures here; the committed tree's verdict is whatever the receipts say today).

_RECEIPT_LANES = {"live-gates": "--live-gates", "live-trade-gates": "--trade-gates",
                  "duo-pairs": "--duo-pairs", "release-evidence": "--release-evidence"}


def test_placeholder_lanes_are_bound_to_real_checks():
    assert gate.UNIMPLEMENTED == {}
    assert _lane("fixtures").argv[1:] == ["tools/verify_gen2_release.py", "--fixtures"]
    assert "fixtures" in gate._SLOW and "P3b" in _lane("fixtures").why
    assert _lane("patch-build").argv[1:] == ["tools/build_gen2_companion.py", "--check"]
    for name, flag in _RECEIPT_LANES.items():
        assert _lane(name).argv[1:] == ["tools/verify_gen2_release.py", flag]
        assert name in gate._SLOW
    for name in ("patch-build", *_RECEIPT_LANES):
        assert "P4" in _lane(name).why or "P6" in _lane(name).why, name
    assert not any("test_gen2_trade_gates.py" in " ".join(lane.argv) for lane in gate.LANES)
    assert gate.manifest_errors() == []


@pytest.mark.parametrize("name", ["fixtures", "patch-build", *_RECEIPT_LANES])
def test_new_lanes_fail_on_missing_inputs_before_running(monkeypatch, tmp_path, name):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate.release_lanes, "run_lane", lambda *_a, **_k: pytest.fail("lane executed"))
    ok, detail = gate.run_lane(_lane(name), quiet=True)
    assert not ok and "missing prerequisites" in detail


@pytest.mark.parametrize(("returncode", "ok"), [(1, False), (0, True)])
def test_patch_build_verdict_is_the_builders_check(monkeypatch, returncode, ok):
    """The builder's --check rebuilds and compares to the published provenance; drift exits 1."""
    seen = []

    def run(argv, **_kwargs):
        seen.append(argv)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(gate.release_lanes.subprocess, "run", run)
    assert gate.run_lane(_lane("patch-build"), quiet=True)[0] is ok
    assert seen[0][1:] == ["tools/build_gen2_companion.py", "--check"]


@pytest.mark.parametrize(("flag", "func"), [("--fixtures", "fixtures_errors"),
                                            ("--live-gates", "live_gates_errors"),
                                            ("--trade-gates", "trade_gates_errors"),
                                            ("--duo-pairs", "duo_pairs_errors"),
                                            ("--release-evidence", "release_evidence_errors")])
def test_receipt_cli_exit_follows_the_gaps(monkeypatch, capsys, flag, func):
    monkeypatch.setattr(gate, func, lambda: ["x: stale"])
    assert gate.main([flag]) == 1
    assert "RED  x: stale" in capsys.readouterr().out
    monkeypatch.setattr(gate, func, lambda: [])
    assert gate.main([flag]) == 0


# live-gates: synthetic panel/sfx/w6 receipts that satisfy the production validators.

def _clock(raw, title, hour=11, now=1790278047):
    import gen2_synth_fixtures as synth
    return synth.day_clock(raw, hour=hour, now=now, title=title)[1]


def _live_gates_tree(tmp_path):
    (tmp_path / "data/gen2").mkdir(parents=True, exist_ok=True)
    provenance = (REPO / "data/gen2/overlay_provenance.json").read_bytes()
    (tmp_path / "data/gen2/overlay_provenance.json").write_bytes(provenance)
    pins = {row["slink_title"]: row["sha1"] for row in json.loads(provenance)["outputs"].values()}
    (tmp_path / "tests/fixtures/gen2/receipts").mkdir(parents=True, exist_ok=True)
    rows = []
    for title in gate.TITLES:
        fixture = f"{title}_battle"
        raw = (REPO / "tests/fixtures/gen2" / f"{fixture}.SaveRAM").read_bytes()
        (tmp_path / "tests/fixtures/gen2" / f"{fixture}.SaveRAM").write_bytes(raw)
        bind = {"result": "PASS", "evidence_level": "PHYSICAL", "title": title, "overlay_sha1": pins[title],
                "fixture": fixture, "fixture_sha256": hashlib.sha256(raw).hexdigest()}
        leg = {"fixture": fixture, "fixture_sha256": bind["fixture_sha256"], "overlay_sha1": pins[title],
               "inner_completed": True, "corpus_frames": 100, "allowed_writes": 3, "violation_count": 0,
               "violations": [], "control": {"native_caught": True, "lua_caught": True}}
        receipts = {
            "panel_gate": {**bind, "schema": "gen2-panel-gate-v1", "minimum_sp": {"margin_bytes": 16}},
            "sfx_gate": {**bind, "schema": "gen2-sfx-gate-v1", "deadline_frames": 300,
                         "contexts": {name: {"result": "PASS", "posted": 0, "fade_end": 0, "played": 9,
                                             "battle_service_gap": 5} for name in gate.SFX_GATE_CONTEXTS},
                         "reset": {"result": "PASS", "pending_at_entry": True, "played_id": None,
                                   "on_channel": None}},
            "w6_gate": {**bind, "schema": "gen2-w6-gate-v1", "violation_count": 0,
                        "legs": {name: {**leg, "clock_setup": _clock(raw, title) if (title, name) in
                                        gate.W6_CLOCK_LEGS else None} for name in gate.W6_GATE_LEGS}},
        }
        for kind, receipt in receipts.items():
            path = tmp_path / "tests/fixtures/gen2/receipts" / f"{title}_overlay.{kind}.json"
            path.write_text(json.dumps(receipt), encoding="utf-8", newline="\n")
            rows.append({"id": f"new-gates.{kind}.{title}", "axes": {"kind": kind, "title": title},
                         "proofs": [{"receipts": {"receipt": {"path": path.relative_to(tmp_path).as_posix(),
                                                              "sha256": _lf_sha(path)}}}]})
    doc = {"requirements": rows}
    (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def test_live_gates_green_only_on_a_valid_tree(tmp_path):
    _live_gates_tree(tmp_path)
    assert gate.live_gates_errors(tmp_path) == []
    assert gate.live_gates_errors(tmp_path / "empty") == [f"{gate.NEW_GATES} missing or malformed"]


def _drop_row(tmp_path, doc):
    doc["requirements"] = [row for row in doc["requirements"] if row["id"] != "new-gates.sfx_gate.gold"]


def _empty_proof(tmp_path, doc):
    doc["requirements"][0]["proofs"] = []


def _delete_receipt(tmp_path, doc):
    (tmp_path / doc["requirements"][1]["proofs"][0]["receipts"]["receipt"]["path"]).unlink()


def _edit_receipt(tmp_path, doc):
    path = tmp_path / doc["requirements"][2]["proofs"][0]["receipts"]["receipt"]["path"]
    path.write_text(path.read_text(encoding="utf-8").replace('"violation_count": 0', '"violation_count": 1', 1),
                    encoding="utf-8")


def _republish_overlay(tmp_path, _doc):
    path = tmp_path / "data/gen2/overlay_provenance.json"
    provenance = json.loads(path.read_text(encoding="utf-8"))
    provenance["outputs"]["pokegold"]["sha1"] = "0" * 40
    path.write_text(json.dumps(provenance), encoding="utf-8")


def _change_fixture(tmp_path, _doc):
    path = tmp_path / "tests/fixtures/gen2/silver_battle.SaveRAM"
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])


@pytest.mark.parametrize("mutation", [_drop_row, _empty_proof, _delete_receipt, _edit_receipt,
                                      _republish_overlay, _change_fixture])
def test_live_gates_red_on_missing_or_stale_receipts(tmp_path, mutation):
    doc = _live_gates_tree(tmp_path)
    mutation(tmp_path, doc)
    (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    assert gate.live_gates_errors(tmp_path) != []


# live-trade-gates: every trade case on every pair, judged by the real trade receipt validator.

_TRADE_FIXTURES = {"gen2_new": {"a": "crystal_battle_errand", "b": "crystal_battle_ot2_errand"},
                   "gen2_gold_silver": {"a": "gold_battle_errand", "b": "silver_battle_errand"},
                   "gen2_crystal_gold": {"a": "crystal_battle_errand", "b": "gold_battle_errand"}}


def _trade_duo():
    scenarios = {name: {"oracle": "assert_gen2_link_saved"} for name in ["link", *gate.TRADE_END_STATUS]}
    duo = _fake_duo(scenarios=scenarios)
    duo.GEN2_TRADE_FIXTURES = dict(_TRADE_FIXTURES)
    return duo


def _trade_tree(tmp_path):
    doc = _green_tree(tmp_path)
    for row in doc["requirements"]:
        row["axes"]["trade_fixtures"] = _TRADE_FIXTURES[row["axes"]["pairing"]]
        row["axes"]["scenarios"] = ["link", *sorted(gate.TRADE_END_STATUS)]
        for scenario in sorted(gate.TRADE_END_STATUS):
            row["proofs"].append(_trade_proof(tmp_path, row["axes"], scenario, f"{row['id']}_{scenario}"))
    _write_doc(tmp_path, doc)
    return doc


def test_trade_gates_green_only_when_every_case_is_receipted(tmp_path):
    doc = _trade_tree(tmp_path)
    assert gate.trade_gates_errors(tmp_path, _trade_duo()) == []
    # The lane is narrowed to trade cells: a missing link proof is a duo-link gap, not a trade gap.
    row = _row(doc, "duo.gold.silver")
    row["proofs"] = [p for p in row["proofs"] if p["scenario"] != "link"]
    _write_doc(tmp_path, doc)
    assert gate.trade_gates_errors(tmp_path, _trade_duo()) == []
    assert gate.duo_matrix_errors(tmp_path, _trade_duo()) != []


def _undeclare_case(tmp_path, doc):
    row = _row(doc, "duo.gold.silver")
    row["axes"]["scenarios"].remove("gen2_trade_timeout")
    row["proofs"] = [p for p in row["proofs"] if p["scenario"] != "gen2_trade_timeout"]


def _unreceipt_case(tmp_path, doc):
    row = _row(doc, "duo.crystal.crystal")
    row["proofs"] = [p for p in row["proofs"] if p["scenario"] != "gen2_trade_refuse_item"]


def _edit_trade_receipt(tmp_path, doc):
    proof = next(p for p in _row(doc, "duo.gold.silver")["proofs"] if p["scenario"] == "gen2_trade_new")
    path = tmp_path / proof["receipts"]["a"]["path"]
    path.write_text(path.read_text(encoding="utf-8").replace("PASS", "FAIL"), encoding="utf-8")


@pytest.mark.parametrize("mutation", [_undeclare_case, _unreceipt_case, _edit_trade_receipt, _republish_overlay])
def test_trade_gates_red_on_missing_or_stale_receipts(tmp_path, mutation):
    doc = _trade_tree(tmp_path)
    mutation(tmp_path, doc)
    _write_doc(tmp_path, doc)
    assert gate.trade_gates_errors(tmp_path, _trade_duo()) != []


def test_committed_trade_gates_are_red_until_trade_duos_are_receipted():
    rows = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))["requirements"]
    receipted = {(row["id"], proof["scenario"]) for row in rows for proof in row["proofs"]}
    if not all((f"duo.{a}.{b}", case) in receipted for a, b in gate.DUO_PAIRS for case in gate.TRADE_END_STATUS):
        assert gate.trade_gates_errors() != []


def test_c_g_owes_every_trade_case_under_o34(tmp_path):
    doc = _trade_tree(tmp_path)
    assert gate.trade_gates_errors(tmp_path, _trade_duo()) == []
    _without(_row(doc, "duo.crystal.gold"), "gen2_trade_new")
    _write_doc(tmp_path, doc)
    assert "duo.crystal.gold: required scenario(s) ['gen2_trade_new'] not declared" in gate.trade_gates_errors(
        tmp_path, _trade_duo())


# duo-pairs: the P3b.7 + trade set on C-C and G-S. Per-cell receipt validators are covered above,
# so this stubs _receipt_errors and checks only which cells the lane demands.

def _pairs_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_receipt_errors", lambda *_a: [])
    need = sorted(gate.DUO_PAIRS_SCENARIOS | set(gate.TRADE_END_STATUS))
    duo = _trade_duo()
    duo.SCENARIOS.update({name: {"oracle": "assert_gen2_link_saved"} for name in need})
    doc = _green_tree(tmp_path)
    for row in doc["requirements"]:
        row["axes"]["scenarios"] = list(need)
        row["axes"]["trade_fixtures"] = _TRADE_FIXTURES[row["axes"]["pairing"]]
        row["proofs"] = [{"scenario": name, "receipts": {}} for name in need]
    _write_doc(tmp_path, doc)
    return doc, duo


def _without(row, name):
    row["axes"]["scenarios"] = [s for s in row["axes"]["scenarios"] if s != name]
    row["proofs"] = [p for p in row["proofs"] if p["scenario"] != name]


def test_duo_pairs_green_only_with_every_p3b7_and_trade_cell(tmp_path, monkeypatch):
    doc, duo = _pairs_tree(tmp_path, monkeypatch)
    assert gate.duo_pairs_errors(tmp_path, duo) == []
    duo.scenarios_for = lambda game: ["link"]
    for row in doc["requirements"]:
        row["axes"]["scenarios"], row["proofs"] = ["link"], [{"scenario": "link", "receipts": {}}]
    _write_doc(tmp_path, doc)
    errors = {e.split(":")[0]: e for e in gate.duo_pairs_errors(tmp_path, duo)}
    assert sorted(errors) == ["duo.crystal.crystal", "duo.crystal.gold", "duo.gold.silver"]
    assert all("required scenario(s)" in e and "gen2_trade_new" in e for e in errors.values())
    # C-G owes the trade cases (O-34) but not the P3b.7 list.
    assert "gen2_ball_gate" in errors["duo.gold.silver"] and "gen2_ball_gate" not in errors["duo.crystal.gold"]


def test_duo_pairs_red_on_an_unreceipted_cell(tmp_path, monkeypatch):
    doc, duo = _pairs_tree(tmp_path, monkeypatch)
    row = _row(doc, "duo.gold.silver")
    row["proofs"] = [p for p in row["proofs"] if p["scenario"] != "gen2_egg_hatch"]
    _write_doc(tmp_path, doc)
    assert gate.duo_pairs_errors(tmp_path, duo) == [
        "duo.gold.silver/gen2_egg_hatch: no receipt registered (an empty proof is a release blocker)"]


def test_shiny_bonus_is_the_recorded_limit_not_a_duo_pairs_cell():
    assert "gen2_shiny_bonus" not in gate.DUO_PAIRS_SCENARIOS
    assert {"link", "gen2_faint", "gen2_faint_active", "gen2_reconnect"} <= gate.DUO_PAIRS_SCENARIOS


# release-evidence: the G4 packet (synthetic published overlay) plus the receipt lanes.

_SIGNED = '| G4 | owner 2026-10-01: "signed" | abc1234 | release-evidence green | none |\n'


def _packet_tree(tmp_path):
    outputs, symbols = {}, {}
    for title in gate.TITLES:
        ups = tmp_path / f"patch/dist/SLink-{title.capitalize()}.ups"
        ups.parent.mkdir(parents=True, exist_ok=True)
        ups.write_bytes(b"UPS1" + title.encode())
        for ext in ("sym", "map"):
            path = tmp_path / "data/gen2" / f"{title}_slink.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{title} {ext}\n".encode())
            symbols[path.name] = _lf_sha(path)
        sha1 = hashlib.sha1(title.encode()).hexdigest()
        ups_pin = {"file": ups.relative_to(tmp_path).as_posix(),
                   "sha256": hashlib.sha256(ups.read_bytes()).hexdigest()}
        outputs[f"poke{title}"] = {"slink_title": title, "sha1": sha1, "ups": ups_pin}
        matrix = tmp_path / f"data/games/gen2_{title}/admission.json"
        matrix.parent.mkdir(parents=True, exist_ok=True)
        matrix.write_text(json.dumps({"artifacts": [
            {"id": f"poke{title}", "kind": "clean", "status": "BUILT"},
            {"id": f"{title}_overlay", "kind": "overlay", "status": "ADMITTED", "sha1": sha1, "ups": ups_pin}]}),
            encoding="utf-8")
    (tmp_path / "data/gen2/overlay_provenance.json").write_text(
        json.dumps({"outputs": outputs, "symbols": symbols}), encoding="utf-8")
    (tmp_path / "docs/gen2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/gen2/PLAN.md").write_text("| Gate | Signed |\n" + _SIGNED, encoding="utf-8")
    return tuple(f"SLink-{title.capitalize()}.ups" for title in gate.TITLES)


def test_g4_packet_green_only_on_a_complete_packet(tmp_path):
    shipped = _packet_tree(tmp_path)
    assert gate.g4_packet_errors(tmp_path, shipped) == []


def _unsign(tmp_path):
    plan = tmp_path / "docs/gen2/PLAN.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(_SIGNED, "| G4 | — | — | — | — |\n"),
                    encoding="utf-8")


def _unadmit(tmp_path):
    path = tmp_path / "data/games/gen2_gold/admission.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"ADMITTED"', '"BUILT"'), encoding="utf-8")


def _stale_admission(tmp_path):
    _republish_overlay(tmp_path, None)


def _edit_ups(tmp_path):
    (tmp_path / "patch/dist/SLink-Silver.ups").write_bytes(b"other")


def _edit_sym(tmp_path):
    (tmp_path / "data/gen2/crystal_slink.map").write_bytes(b"other\n")


def _missing_provenance(tmp_path):
    (tmp_path / "data/gen2/overlay_provenance.json").unlink()


@pytest.mark.parametrize("mutation", [_unsign, _unadmit, _stale_admission, _edit_ups, _edit_sym,
                                      _missing_provenance, "unshipped"])
def test_g4_packet_red_on_each_missing_piece(tmp_path, mutation):
    shipped = _packet_tree(tmp_path)
    if mutation == "unshipped":
        shipped = shipped[:2]
    else:
        mutation(tmp_path)
    assert gate.g4_packet_errors(tmp_path, shipped) != []


_PARTS = ("g4_packet_errors", "stale_errors", "new_gates_errors", "live_gates_errors", "trade_gates_errors",
          "duo_pairs_errors")


@pytest.mark.parametrize("red", [None, *_PARTS])
def test_release_evidence_is_green_only_when_every_part_is(monkeypatch, red):
    for part in _PARTS:
        monkeypatch.setattr(gate, part, lambda *_a, _p=part, **_k: [f"{_p} gap"] if _p == red else [])
    errors = gate.release_evidence_errors()
    assert errors == [] if red is None else len(errors) == 1 and errors[0].endswith(f"{red} gap")


def test_committed_g4_packet_is_red_until_the_owner_signs():
    plan = (REPO / "docs/gen2/PLAN.md").read_text(encoding="utf-8")
    if "| G4 | — |" in plan:
        assert "docs/gen2/PLAN.md §6.1: the G4 ledger row carries no owner signature" in gate.g4_packet_errors()


# DUO-WAVE-C (whiteout, pc_ops, changebox, poison): the PYDEC line names its own cell's tokens.
_WAVE_C_PYDEC = {
    "gen2_whiteout": ("memorial", "scenario=gen2_whiteout repair=run_over", "repair=memorial_first"),
    "gen2_pc_ops": ("alive", "scenario=gen2_pc_ops release=unpropagated", "release=propagated"),
    "gen2_changebox": ("memorial", "scenario=gen2_changebox box_change=BOX1->BOX14->BOX1", "box_change=BOX1"),
    "gen2_poison": ("dead", "scenario=gen2_poison death=poison", "death=battle"),
    "gen2_whiteout_rebuild": ("alive", "scenario=gen2_whiteout_rebuild rebuild=restored", "rebuild=lost"),
}


@pytest.mark.parametrize("scenario", sorted(_WAVE_C_PYDEC))
def test_wave_c_pydec_requires_its_scenario_tokens(scenario):
    status, tokens, wrong = _WAVE_C_PYDEC[scenario]
    axes = {"initiator": "gold", "partner": "silver"}
    keys = {"a": "AAAA:1111:01", "b": "BBBB:2222:02"}
    head = f"PYDEC: PASS a={keys['a']} b={keys['b']} area=route_29 titles=gold/silver status={status}"
    assert gate._pydec_cell_errors([f"{head} {tokens}"], scenario, axes, keys) == []
    assert gate._pydec_cell_errors([head], scenario, axes, keys) != []
    bad = f"{head} {tokens.rsplit(' ', 1)[0]} {wrong}"
    assert gate._pydec_cell_errors([bad], scenario, axes, keys) != []
    assert gate._pydec_cell_errors([f"{head.replace(status, 'alive' if status != 'alive' else 'dead')} {tokens}"],
                                   scenario, axes, keys) != []


@pytest.mark.parametrize(("scenario", "sides"), [("gen2_changebox", ["a", "b"]), ("gen2_whiteout", []),
                                                 ("gen2_pc_ops", [])])
def test_changebox_memorial_needs_the_hp_zero_preimage_but_whiteout_does_not(monkeypatch, scenario, sides):
    """DUO-WAVE-C: changebox's memorial is the faint half; whiteout's preimage is the REVIVED record."""
    seen = []
    monkeypatch.setattr(gate, "_memorial_receipt_errors", lambda _lines, side: seen.append(side) or [])
    axes = {"initiator": "crystal", "partner": "crystal", "fixtures": {"a": "x", "b": "y"}}
    gate._receipt_errors(REPO, {"receipts": {}}, scenario, axes, {})
    assert seen == sides


def test_contest_refusal_is_model_only_and_its_named_tests_exist():
    """Coordinator ruling: the contest refusal is unreachable in real play; its evidence is the
    named unit tests, and declaring it as a duo cell is a gap on every matrix lane."""
    for name, tests in gate.TRADE_MODEL_ONLY.items():
        assert name not in gate.TRADE_END_STATUS
        for node in tests:
            path, func = node.split("::")
            assert f"def {func}(" in (REPO / path).read_text(encoding="utf-8"), node
    doc = json.loads((REPO / gate.DUO_MATRIX).read_text(encoding="utf-8"))
    assert not any(set(gate.TRADE_MODEL_ONLY) & set(row["axes"]["scenarios"]) for row in doc["requirements"])


def test_a_model_only_case_declared_as_a_cell_is_red(tmp_path):
    doc = _trade_tree(tmp_path)
    _row(doc, "duo.gold.silver")["axes"]["scenarios"].append("gen2_trade_refuse_contest")
    _write_doc(tmp_path, doc)
    for errors in (gate.trade_gates_errors(tmp_path, _trade_duo()), gate.duo_matrix_errors(tmp_path, _trade_duo())):
        assert any("duo.gold.silver: ['gen2_trade_refuse_contest'] are MODEL-only" in e for e in errors)


# clock-setup-v1: a W6 leg's O-33 clock setup must re-derive from the committed fixture (day_clock).

def _w6_leg(tmp_path, doc, title="silver", leg="u1"):
    row = next(r for r in doc["requirements"] if r["id"] == f"new-gates.w6_gate.{title}")
    entry = row["proofs"][0]["receipts"]["receipt"]
    path = tmp_path / entry["path"]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    def save():
        path.write_text(json.dumps(receipt), encoding="utf-8")
        _repin(tmp_path, entry)
        (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")

    return receipt, receipt["legs"][leg], save


def test_w6_clock_setup_rederives_from_the_fixture(tmp_path):
    doc = _live_gates_tree(tmp_path)
    assert gate.live_gates_errors(tmp_path) == []
    receipt, leg, save = _w6_leg(tmp_path, doc)
    assert leg["clock_setup"]["schema"] == "gen2-clock-setup-v1" and leg["clock_setup"]["title"] == "silver"


@pytest.mark.parametrize("mutation", ["delete", "game_hour", "host_time", "new_hex", "old_hex", "sha256",
                                      "cartram_sha256", "base_sha256", "start_time", "schema", "retarget_title",
                                      "retarget_fixture", "legacy_ten_oclock"])
def test_w6_clock_setup_red_when_deleted_falsified_or_retargeted(tmp_path, mutation):
    doc = _live_gates_tree(tmp_path)
    receipt, leg, save = _w6_leg(tmp_path, doc)
    setup = leg["clock_setup"]
    if mutation == "delete":
        leg["clock_setup"] = None
    elif mutation == "game_hour":
        setup["game_hour"] = 12
    elif mutation == "host_time":
        setup["host_time"] += 3600
    elif mutation in ("new_hex", "old_hex"):
        setup[mutation] = setup[mutation][:-2] + ("00" if setup[mutation][-2:] != "00" else "01")
    elif mutation in ("sha256", "cartram_sha256", "base_sha256"):
        setup[mutation] = "0" * 64
    elif mutation == "start_time":
        setup["start_time"] = [10, 0, 0]
    elif mutation == "schema":
        setup["schema"] = "gen2-synth-disclosure-v1"
    elif mutation == "retarget_title":
        setup["title"] = "gold"
    elif mutation == "retarget_fixture":
        leg["clock_setup"] = _clock((REPO / "tests/fixtures/gen2/gold_battle.SaveRAM").read_bytes(), "gold")
    else:   # the pre-fix disclosure: game = 10:00 + RTC, which the saved 09:58:55 start contradicts
        setup.update(start_time=[10, 0, 0], schema="gen2-synth-disclosure-v1")
    save()
    errors = gate.live_gates_errors(tmp_path)
    assert any("new-gates.w6_gate.silver: w6 gate leg u1" in e and "clock setup" in e for e in errors), errors


def test_any_other_legs_clock_setup_obeys_the_same_rule(tmp_path):
    doc = _live_gates_tree(tmp_path)
    receipt, leg, save = _w6_leg(tmp_path, doc, title="gold", leg="panel")
    leg["clock_setup"] = _clock((REPO / "tests/fixtures/gen2/gold_battle.SaveRAM").read_bytes(), "gold", hour=14)
    save()
    assert gate.live_gates_errors(tmp_path) == []
    leg["clock_setup"]["game_hour"] = 15
    save()
    assert any("new-gates.w6_gate.gold: w6 gate leg panel: clock setup" in e for e in gate.live_gates_errors(tmp_path))
