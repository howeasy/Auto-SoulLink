"""Gen 2 manifest contracts; synthetic results are MODEL, never cartridge evidence."""
from __future__ import annotations

import hashlib
import json
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
        "live-gates", "live-new-gates", "live-trade-gates", "duo-pairs", "release-evidence",
    ]
    assert gate.manifest_errors() == []
    for title in ("crystal", "gold", "silver"):
        assert _lane(f"profile-generated-{title}").argv[-3:] == ["--title", title, "--check"]
    assert "--check" in _lane("source-build").argv


def test_live_new_gates_lane_targets_the_p3b3a_inspect_driver():
    """P3b.3a landed lua/tests/gen2_inspect_gate.lua and tests/live/test_gen2_new_gates.py; this
    lane's argv already names that file (nothing to rename), it stays UNIMPLEMENTED because the
    lane's full requirement mapping also needs the engine-site/write/client rows no card has
    landed yet, and its why= now says so instead of describing the whole file as absent."""
    lane = _lane("live-new-gates")
    assert "tests/live/test_gen2_new_gates.py" in lane.argv
    assert (Path(__file__).resolve().parents[2] / "tests/live/test_gen2_new_gates.py").exists()
    assert "P3b.3a" in lane.why and "inspect" in lane.why
    assert "live-new-gates" in gate.UNIMPLEMENTED
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
    assert "release-evidence" in gate.UNIMPLEMENTED
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
    assert "UNIMPLEMENTED" in out
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
        monkeypatch.setattr(gate, "UNIMPLEMENTED", {
            name: reason for name, reason in gate.UNIMPLEMENTED.items()
            if name != "release-evidence"
        })
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


@pytest.mark.parametrize("name", [
    "fixtures", "patch-build", "live-gates", "live-new-gates", "live-trade-gates",
    "duo-pairs", "release-evidence",
])
def test_future_binding_cannot_pass_by_merely_adding_a_file(monkeypatch, tmp_path, name):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    lane = _lane(name)
    for arg in lane.argv:
        if arg.endswith(".py"):
            target = tmp_path / arg
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# not a qualified implementation\n", encoding="utf-8")
    monkeypatch.setattr(gate.release_lanes, "run_lane",
                        lambda *_args, **_kwargs: pytest.fail("unimplemented lane executed"))
    ok, detail = gate.run_lane(lane, quiet=True)
    assert not ok
    assert detail.startswith("UNIMPLEMENTED:")


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


def test_full_skeleton_cannot_pass_when_source_lanes_are_green(monkeypatch, capsys):
    real_binding = gate.run_lane

    def source_passes(lane, quiet):
        if lane.name in gate.UNIMPLEMENTED:
            return real_binding(lane, quiet)
        return True, "synthetic source/MODEL pass"

    monkeypatch.setattr(gate, "run_lane", source_passes)
    assert gate.main([]) == 1
    out = capsys.readouterr().out
    assert "GATE FAILED" in out
    assert "UNIMPLEMENTED" in out
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
