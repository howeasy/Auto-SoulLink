"""Trade-lane integration boundaries; no emulator or server processes are launched."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import e2e_duo as duo  # noqa: E402
import gen2_trade_oracles as oracle  # noqa: E402

from patch.tools.make_ups import ups_apply  # noqa: E402
from tools.gen2_trade_lane import SCENARIOS, validate_manifest  # noqa: E402

GAMES = ("gen2_new", "gen2_gold_silver", "gen2_crystal_gold")


def _run(monkeypatch, tmp_path, game="gen2_new", scenario="gen2_trade_new", lane="trade-model"):
    build, data = tmp_path / "build", tmp_path / lane
    build.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(duo, "BUILD", str(build))
    monkeypatch.setattr(duo, "free_port", lambda: 54329)
    monkeypatch.setattr(duo.tempfile, "mkdtemp", lambda **_kw: str(data))
    args = argparse.Namespace(game=game, scenario=scenario, lane=lane, idle_jitter=0, server_flags=[], keep_data=True)
    return duo.DuoRun(scenario, args)


@pytest.mark.parametrize("game", GAMES)
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_trade_scenarios_require_the_trade_oracle_and_overlay(game, scenario):
    assert scenario in duo.scenarios_for(game)
    row = duo.SCENARIOS[scenario]
    assert row["artifact_kind"] == "overlay" and row["oracle"] == "assert_gen2_trade_saved"
    assert duo.evidence_contract(game).require_oracle
    assert duo.evidence_contract(game).witness_validator == "check_gen2_save_witness"
    assert scenario not in duo.scenarios_for("gen1_new")


@pytest.mark.parametrize("game", GAMES)
def test_missing_trade_errand_declaration_fails_before_any_launch(monkeypatch, game):
    from tools import gen2_fixtures, gen2_source_data

    name = duo.GEN2_TRADE_FIXTURES[game]["a"]
    monkeypatch.delitem(gen2_fixtures.BY_NAME, name, raising=False)
    monkeypatch.setattr(gen2_source_data, "load_context", lambda *a, **k: pytest.fail("unexpected ROM access"))
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected process launch"))
    with pytest.raises(FileNotFoundError, match=name):
        duo.gen2_preflight(game=game, scenario="gen2_trade_new")


def test_missing_trade_errand_file_is_not_replaced_by_a_battle_fixture(monkeypatch, tmp_path):
    from tools import gen2_fixtures, gen2_source_data

    name = duo.GEN2_TRADE_FIXTURES["gen2_new"]["a"]
    context = gen2_source_data.load_context("crystal", root=ROOT)
    monkeypatch.setitem(gen2_fixtures.BY_NAME, name, SimpleNamespace(title="crystal"))
    monkeypatch.setattr(gen2_source_data, "load_context", lambda *a, **k: context)
    with pytest.raises(FileNotFoundError, match=name):
        duo.gen2_preflight(repo=tmp_path, game="gen2_new", scenario="gen2_trade_new")


@pytest.mark.parametrize("missing", ["driver", "witness", "oracle"])
def test_missing_trade_runtime_component_refuses_before_launch(monkeypatch, tmp_path, missing):
    run = _run(monkeypatch, tmp_path)
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    emulator = tmp_path / "emulator-placeholder"
    emulator.write_bytes(b"not executable")
    monkeypatch.setattr(duo, "EMUHAWK", str(emulator))
    monkeypatch.setattr(duo, "gen2_preflight", lambda **kwargs: {})
    run._prepare_gen2_trade_manifest = lambda: None  # Isolate the later driver/oracle existence boundary.
    paths = [run.gcfg["main"], "lua/tests/duo/gen2_route29_inputs.lua",
             "lua/tests/duo/gen2_trade.lua", "tools/gen2_trade_facts.py"]
    if missing != "driver":
        paths.append("lua/tests/duo/scenario_gen2_trade_new.lua")
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("-- MODEL existence fixture\n")
    callbacks = {"check_trade_witness": lambda *a, **k: None, "trade_oracle": lambda *a, **k: None}
    if missing != "driver":
        del callbacks["check_trade_witness" if missing == "witness" else "trade_oracle"]
    monkeypatch.setitem(sys.modules, "gen2_trade_oracles", SimpleNamespace(**callbacks))
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *a, **k: pytest.fail("incomplete lane launched"))
    message = "driver missing" if missing == "driver" else "oracle implementation missing"
    with pytest.raises((FileNotFoundError, RuntimeError), match=message):
        run._prepare_gen2_lane()


def _real_stages(run):
    provenance = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text())
    lock = json.loads((ROOT / "data/gen2_sources.lock.json").read_text())
    run._gen2_inputs, run._gen2_plans = {}, {}
    for side, title in zip(("a", "b"), {"gen2_new": ("crystal", "crystal"),
            "gen2_gold_silver": ("gold", "silver"), "gen2_crystal_gold": ("crystal", "gold")}[run.game], strict=True):
        artifact = "poke" + title
        out = provenance["outputs"][artifact]
        repo = "pokecrystal" if title == "crystal" else "pokegold"
        base = (ROOT / ".cache/gen2-build" / repo / lock["outputs"][artifact]["filename"]).read_bytes()
        stage = ups_apply(base, (ROOT / out["ups"]["file"]).read_bytes())
        fixture = Path(run.data_dir) / f"{side}.SaveRAM"
        fixture.write_bytes(side.encode() * 32790)
        run._gen2_inputs[side] = {"title": title, "rom_sha1": out["base_sha1"], "fixture": fixture,
                                   "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
        run._gen2_plans[side] = {"stage": stage, "launch_sha1": out["sha1"],
            "rom": Path(duo.BUILD) / f"gen2_{title}_overlay.gbc", "directory": Path(run._saveram_dir(side)),
            "saveram_name": f"gen2_{title}_overlay.SaveRAM", "env": {"SLINK_GEN2_TITLE": title}}


@pytest.mark.parametrize("game", GAMES)
def test_manifest_staging_is_hash_bound_and_seed_directories_are_isolated(monkeypatch, tmp_path, game):
    run = _run(monkeypatch, tmp_path, game)
    _real_stages(run)
    run._prepare_gen2_trade_manifest()
    path = run._gen2_trade_manifest_path
    assert path.parent == Path(run.data_dir)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == run._gen2_trade_manifest_sha256
    assert validate_manifest(path) == run._gen2_trade_manifest
    saves = {side: Path(run._seed_instance_save(side)) for side in ("a", "b")}
    assert saves["a"].parent != saves["b"].parent and saves["a"].read_bytes() != saves["b"].read_bytes()
    for side, plan in run._gen2_plans.items():
        assert plan["rom"].is_relative_to(Path(duo.BUILD))
        assert hashlib.sha1(plan["rom"].read_bytes()).hexdigest() == plan["launch_sha1"]
        assert run._gen2_inputs[side]["rom_sha1"] == plan["launch_sha1"]
        assert run._gen2_inputs[side]["source_rom_sha1"] == run._gen2_trade_manifest["players"][side]["base_sha1"]
    ref = run._gen2_trade_overlay_reference()
    assert ref["manifest_path"] == str(path) and ref["manifest_sha256"] == run._gen2_trade_manifest_sha256
    assert (Path(run.data_dir) / "trade_evidence").is_dir()


@pytest.mark.parametrize("fault", ["stage", "base", "escape", "existing_manifest"])
def test_manifest_staging_refuses_bad_inputs_and_clobber(monkeypatch, tmp_path, fault):
    run = _run(monkeypatch, tmp_path)
    _real_stages(run)
    if fault == "stage":
        run._gen2_plans["a"]["stage"] = b"bad overlay"
    elif fault == "base":
        run._gen2_inputs["a"]["rom_sha1"] = "0" * 40
    elif fault == "escape":
        run._gen2_plans["a"]["rom"] = tmp_path / "outside-build.gbc"
    else:
        (Path(run.data_dir) / "gen2_trade_manifest.json").write_bytes(b"existing evidence")
    with pytest.raises((RuntimeError, FileExistsError)):
        run._prepare_gen2_trade_manifest()
    if fault == "existing_manifest":
        assert (Path(run.data_dir) / "gen2_trade_manifest.json").read_bytes() == b"existing evidence"


def test_server_launch_uses_private_trade_bootstrap(monkeypatch, tmp_path):
    run = _run(monkeypatch, tmp_path)
    run._gen2_trade_manifest_path = Path(run.data_dir) / "manifest.json"
    launched = []
    monkeypatch.setattr(duo.subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw)) or SimpleNamespace())
    run.wait_for = lambda *args: True
    run.start_server()
    cmd, kw = launched[0]
    kw["stdout"].close()
    assert cmd[1:6] == ["-m", "tools.gen2_trade_lane", "--manifest", str(run._gen2_trade_manifest_path), "--"]
    assert cmd[cmd.index("--data-dir") + 1] == run.data_dir
    assert kw["cwd"] == duo.REPO


def test_trade_rom_tamper_is_refused_before_popen(monkeypatch, tmp_path):
    import run_gb_gate

    run = _run(monkeypatch, tmp_path)
    _real_stages(run)
    run._prepare_gen2_trade_manifest()
    run._gen2_env = {"a": {}, "b": {}}
    run._apply_lane_window = lambda _path: None
    monkeypatch.setitem(run_gb_gate.GENS["gen2"], "config", lambda _plan, path: path.write_text("{}"))
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *a, **kw: pytest.fail("tampered ROM launched"))
    run._gen2_plans["a"]["rom"].write_bytes(b"tampered after preflight")
    with pytest.raises(RuntimeError, match="changed before launch"):
        run.launch_instance("a")


def _barrier(run):
    evidence = Path(run.data_dir) / "trade_evidence"
    evidence.mkdir(exist_ok=True)
    (Path(run.data_dir) / "links.json").write_bytes(b'{"links":[]}\n')
    texts, raw = {}, {}
    for i, side in enumerate(("a", "b"), 1):
        raw[side] = bytes([i]) * 32790
        path = Path(run.data_dir) / f"{side}_driver_baseline.SaveRAM"
        path.write_bytes(raw[side])
        image = {"frame": 100, "snapshot_path": str(path), "snapshot_bytes": 32790, "cartram_bytes": 32768,
                 "snapshot_sha256": hashlib.sha256(raw[side]).hexdigest(),
                 "cartram_sha256": hashlib.sha256(raw[side][:32768]).hexdigest()}
        texts[side] = "TRADE_BASELINE " + json.dumps(image) + "\nTRADE_READY " + json.dumps({
            "frame": 101, "snapshot_sha256": image["snapshot_sha256"]}) + "\n"
    return texts, raw


def test_trade_ready_barrier_freezes_both_saves_and_links_before_go(monkeypatch, tmp_path):
    run = _run(monkeypatch, tmp_path)
    texts, raw = _barrier(run)
    visible = {"a": texts["a"], "b": ""}
    monkeypatch.setattr(duo, "read_result", lambda name, side: visible[side])

    def wait(_name, pred, _timeout):
        assert pred() is None, "A alone must not release the barrier"
        assert not list(Path(run.data_dir, "trade_evidence").iterdir())
        visible["b"] = texts["b"].rstrip("\n")[:-3]
        assert pred() is None, "an incomplete flushed READY line must not release the barrier"
        visible["b"] = texts["b"]
        return pred()

    def go(lines):
        assert lines == {"a": ["TRADE_GO"], "b": ["TRADE_GO"]}
        assert {side: path.read_bytes() for side, path in run._gen2_trade_baseline_saves.items()} == raw
        ref = run._gen2_trade_baseline_links
        saved = Path(ref["path"]).read_bytes()
        assert saved == b'{"links":[]}\n' and hashlib.sha256(saved).hexdigest() == ref["sha256"]

    run.wait_for, run.go = wait, go
    run._release_gen2_trade()
    for side in ("a", "b"):
        (Path(run.data_dir) / f"{side}_driver_baseline.SaveRAM").write_bytes(b"later mutable state")
        assert run._gen2_trade_baseline_saves[side].read_bytes() == raw[side]


@pytest.mark.parametrize("fault", ["missing_ready", "bad_ready_hash", "changed_image", "missing_links"])
def test_trade_barrier_never_releases_incomplete_evidence(monkeypatch, tmp_path, fault):
    run = _run(monkeypatch, tmp_path)
    texts, _ = _barrier(run)
    if fault == "missing_ready":
        texts["b"] = ""
    elif fault == "bad_ready_hash":
        mark = oracle._one(texts["b"], "TRADE_READY")
        texts["b"] = texts["b"].replace(json.dumps(mark), json.dumps({**mark, "snapshot_sha256": "0" * 64}))
    elif fault == "changed_image":
        (Path(run.data_dir) / "b_driver_baseline.SaveRAM").write_bytes(b"changed")
    else:
        (Path(run.data_dir) / "links.json").unlink()
    monkeypatch.setattr(duo, "read_result", lambda name, side: texts[side])

    def wait(_name, pred, _timeout):
        result = pred()
        if result is None:
            raise TimeoutError("missing second ready")
        return result

    run.wait_for = wait
    run.go = lambda *_: pytest.fail("released incomplete trade evidence")
    with pytest.raises((RuntimeError, FileNotFoundError, TimeoutError)):
        run._release_gen2_trade()


@pytest.mark.parametrize("bad_scope", [False, True])
@pytest.mark.parametrize("scenario", ["gen2_trade_new", "gen2_trade_reset_commit"])
def test_trade_oracle_wrapper_passes_frozen_inputs_and_requires_scope(monkeypatch, tmp_path, bad_scope, scenario):
    run = _run(monkeypatch, tmp_path, scenario=scenario)
    _real_stages(run)
    run._prepare_gen2_trade_manifest()
    run._gen2_trade_baseline_saves = {side: Path(run.data_dir) / f"{side}.SaveRAM" for side in ("a", "b")}
    run._gen2_trade_baseline_links = {"path": str(Path(run.data_dir) / "before.json"), "sha256": "a" * 64}
    journal = b'{"message":{"event":"trade_offer"},"outcome":{"pending_trade":{"token":"t8","phase":"confirming"}}}\n'
    Path(run.data_dir, "trade_lane_events.jsonl").write_bytes(journal)
    status = {"trade_problem": None, "trade_last": {"token": "t8", "outcome": "committed"}}
    events = b'[{"type":"trade_committed","key":"t8"}]\n'
    run._status = lambda: status
    Path(run.data_dir, "events.json").write_bytes(events)
    results = dict.fromkeys(("a", "b"), 'RECEIPT {"token":"01000000"}\n')
    seen = []

    def checked(res, **kwargs):
        assert res is results
        seen.append(kwargs)
        facts = {"scenario": run.scenario, "admission_scope": "PRODUCTION" if bad_scope else "HARNESS_ONLY_OVERLAY",
                 "area_id": "route_29", "status": "committed",
                 "players": {side: {"title": "crystal", "key": side + "-key"} for side in ("a", "b")}}
        kwargs["on_verified"](facts)
        return "verified"

    monkeypatch.setitem(sys.modules, "gen2_trade_oracles", SimpleNamespace(_one=oracle._one, trade_oracle=checked))
    if bad_scope:
        with pytest.raises(RuntimeError, match="harness scope"):
            run.assert_gen2_trade_saved(results)
        return
    assert run.assert_gen2_trade_saved(results) == "verified"
    call = seen[0]
    assert call["baseline_saves"] is run._gen2_trade_baseline_saves
    assert call["overlay_provenance"] == run._gen2_trade_overlay_reference()
    assert call["expected_case"] == run._gen2_trade_expected_case()
    tx = call["transaction_evidence"]
    assert tx["server_token"] == "t8" and tx["baseline_links"] == run._gen2_trade_baseline_links
    assert Path(tx["events"]["path"]).read_bytes() == journal
    assert tx["events"]["sha256"] == hashlib.sha256(journal).hexdigest()
    if scenario == "gen2_trade_reset_commit":
        refs = tx["reconciliation"]
        assert set(refs) == {"status", "events"}
        for label, ref in refs.items():
            frozen = Path(ref["path"]).read_bytes()
            assert hashlib.sha256(frozen).hexdigest() == ref["sha256"]
            assert json.loads(frozen) == (status if label == "status" else json.loads(events))
        Path(run.data_dir, "events.json").write_bytes(b"[]")
        assert Path(refs["events"]["path"]).read_bytes() == events
    else:
        assert "reconciliation" not in tx
    assert run._gen2_verified_facts["admission_scope"] == "HARNESS_ONLY_OVERLAY"


def test_trade_witness_wrapper_receives_actual_case_and_overlay_pins(monkeypatch, tmp_path):
    run = _run(monkeypatch, tmp_path, scenario="gen2_trade_decline_new")
    _real_stages(run)
    run._prepare_gen2_trade_manifest()
    results = {"a": "A", "b": "B"}
    seen = []
    monkeypatch.setitem(sys.modules, "gen2_trade_oracles", SimpleNamespace(
        check_trade_witness=lambda res, **kw: seen.append((res, kw))))
    run.check_gen2_save_witness(results)
    assert seen == [(results, {"expected_case": run._gen2_trade_expected_case(),
                               "overlay_provenance": run._gen2_trade_overlay_reference()})]
    assert seen[0][1]["expected_case"]["required_phases"] == ["wait"]


def _stub(monkeypatch, run, side):
    import run_gb_gate

    run._gen2_env = {"a": {}, "b": {}}
    run._apply_lane_window = lambda _path: None
    run._rom_for = lambda _inst: "rom"
    run.go_files = {s: str(Path(run.data_dir) / f"go_{s}.txt") for s in ("a", "b")}
    monkeypatch.setitem(run_gb_gate.GENS["gen2"], "config", lambda _plan, path: path.write_text("{}"))
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=1))
    run.launch_instance(side)
    return Path(run.stub_path(side)).read_text()


@pytest.mark.parametrize(("game", "variant"), [("gen2_new", "cc"), ("gen2_gold_silver", "gs"), ("gen2_crystal_gold", "cg")])
@pytest.mark.parametrize("scenario", ["gen2_trade_new", "gen2_trade_reset_commit", "gen2_trade_evolve"])
def test_trade_stub_carries_every_field_the_driver_reads(monkeypatch, tmp_path, game, variant, scenario):
    run = _run(monkeypatch, tmp_path, game, scenario)
    _real_stages(run)
    run._prepare_gen2_trade_manifest()
    for side in ("a", "b"):
        text = _stub(monkeypatch, run, side)
        fields = dict(line.strip().rstrip(",").split(" = ", 1) for line in text.splitlines()
                      if line.startswith("  ") and " = " in line)
        assert fields["variant"] == f'"{variant}"' and fields["trade_case"] == f'"{scenario}"'
        assert fields["trade_manifest_sha256"] == f'"{run._gen2_trade_manifest_sha256}"'
        assert fields["trade_manifest"].strip('"') == str(run._gen2_trade_manifest_path).replace("\\", "/")
        assert fields["trade_evidence_dir"].strip('"').endswith("/trade_evidence")
        assert fields["partner_result"].strip('"') == run._result_path("b" if side == "a" else "a").replace("\\", "/")
        frames = int(fields["timeout_frames"])
        # driver FOR CODEX 4: the reset_commit proposer waits out the server watchdog; everyone else > 150000
        assert frames == (600000 if scenario == "gen2_trade_reset_commit" and side == "a" else 432000)


def test_trade_route_facts_come_from_the_errand_spec(monkeypatch, tmp_path):
    """Driver FOR CODEX 2: an errand fixture plays on spec_route_facts(BY_NAME[name]), not route_facts(title)."""
    import run_gb_gate

    import tests.live.test_gen2_frame_align as align
    import tests.live.test_gen2_new_gates as gates
    from tools import gen2_fixtures, gen2_source_data, gen2_trade_facts

    run = _run(monkeypatch, tmp_path)
    emulator = tmp_path / "EmuHawk.exe"
    emulator.write_bytes(b"")
    monkeypatch.setattr(duo, "EMUHAWK", str(emulator))
    names = duo.GEN2_TRADE_FIXTURES["gen2_new"]
    monkeypatch.setattr(duo, "gen2_preflight", lambda **kw: {side: {
        "name": names[side], "title": "crystal", "fixture": tmp_path / f"{side}.SaveRAM",
        "qualification_attempt_id": "q"} for side in ("a", "b")})
    (tmp_path / "a.SaveRAM").write_bytes(b"a")
    (tmp_path / "b.SaveRAM").write_bytes(b"b")
    monkeypatch.setitem(run_gb_gate.GENS["gen2"], "plan", lambda *a: {"env": {}})
    run._prepare_gen2_trade_manifest = lambda: (setattr(run, "_gen2_trade_manifest_path", tmp_path / "m.json"),
                                                setattr(run, "_gen2_trade_manifest_sha256", "0" * 64))
    monkeypatch.setattr(gen2_source_data, "load_context", lambda *a, **k: None)
    monkeypatch.setattr(gen2_fixtures, "route_facts", lambda *a, **k: pytest.fail("title route facts for an errand"))
    seen = []
    monkeypatch.setattr(gen2_fixtures, "spec_route_facts", lambda spec, root=None: seen.append(spec.name) or {})
    monkeypatch.setattr(gates, "inspect_env", lambda *a, **k: {"SLINK_GEN2_FIXTURE_CASE": "{}"})
    monkeypatch.setattr(align, "u1_facts", lambda *a: {})
    monkeypatch.setattr(gen2_trade_facts, "trade_facts", lambda title, root=None: {"title": title})
    run._prepare_gen2_lane()
    assert seen == [names["a"], names["b"]]
    assert json.loads(run._gen2_env["a"]["SLINK_GEN2_TRADE_FACTS"]) == {"title": "crystal"}


@pytest.mark.parametrize("scenario", ["gen2_trade_new", "gen2_trade_evolve"])
def test_committed_trade_cases_require_every_native_phase(monkeypatch, tmp_path, scenario):
    run = _run(monkeypatch, tmp_path, scenario=scenario)
    _real_stages(run)
    assert run._gen2_trade_expected_case()["required_phases"] == ["wait", "trade_animation", "native_save"]
