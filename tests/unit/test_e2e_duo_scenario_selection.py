"""The duo runner picks the right scenarios for `--game`.

`tools/e2e_duo.py` declared a per-scenario `games` key, documented it, and then read it
nowhere: `--scenario all` expanded to the whole table no matter which title was launched. So
`--game gen1 --scenario all` — a command the project's own docs give — booted two Game Boys
and fed them Radical Red scenarios, which died on a savestate no GB fixture has. The key was
load-bearing in exactly one place, `tests/e2e/test_duo.py`, which had hand-rolled its own copy
of the question with a *different* default and so answered it correctly by luck.

These are pure table lookups: no emulator, no server, no ROM. That is the point — the bug they
cover cost several minutes of two-emulator wall-clock per wrong scenario to discover.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import e2e_duo as duo_module  # noqa: E402
from e2e_duo import (  # noqa: E402
    GAMES,
    SCENARIOS,
    DuoRun,
    list_lines as duo_list_lines,
    scenario_applies,
    scenario_attempt_limit,
    scenarios_for,
)

EXPECTED_GEN2 = ["link", "gen2_faint", "gen2_whiteout", "gen2_pc_ops", "gen2_changebox", "gen2_poison",
                 "gen2_whiteout_rebuild", "gen2_boxed_capture", "gen2_gift", "gen2_egg_hatch", "gen2_npc_trade",
                 "gen2_evolution",
                 "gen2_ball_gate",
                 "gen2_faint_active", "gen2_faint_active_trainer", "gen2_admit_wrong_rom", "gen2_reconnect", "gen2_type_clause",
                 "gen2_gender_clause", "gen2_species_clause", "gen2_soft_reset"]
EXPECTED_GEN2_TRADE = ["gen2_trade_decline_new", "gen2_trade_evolve", "gen2_trade_new", "gen2_trade_refuse_item",
                       "gen2_trade_reset_commit", "gen2_trade_reset_wait", "gen2_trade_timeout"]


def test_family_evidence_contracts_are_explicit_and_aliases_share_one():
    required = duo_module.evidence_contract("gen1_new")
    assert required.require_oracle is True
    assert required.witness_validator == "check_save_witness"
    for game in GAMES:
        contract = duo_module.evidence_contract(game)
        if game.startswith("gen1"):
            assert contract is required
        elif GAMES[game].get("game", game) == "gen2_new":
            assert contract.require_oracle is True
            assert contract.witness_validator
            assert callable(getattr(DuoRun, contract.witness_validator, None))
        else:
            assert contract == duo_module.EvidenceContract()


@pytest.mark.parametrize("fault", (None, "wrong_rom"))
def test_gen2_refusal_preflight_binds_crystal11(monkeypatch, tmp_path, fault):
    import hashlib
    import json
    from types import SimpleNamespace

    from tests.live import test_gen2_new_gates as gates
    from tools import gen2_source_data

    saves = tmp_path / "tests/fixtures/gen2"
    (saves / "receipts").mkdir(parents=True)
    for name in ("crystal_battle", "crystal_battle_ot2"):
        (saves / f"{name}.SaveRAM").write_bytes(name.encode())
        (saves / "receipts" / f"{name}.qualification.json").write_text(json.dumps({"attempt_id": name}))
    rom = tmp_path / "pokecrystal.gbc"
    wrong = tmp_path / "pokecrystal11.gbc"
    rom.write_bytes(b"admitted")
    wrong.write_bytes(b"refused")
    admitted_hash = hashlib.sha1(rom.read_bytes()).hexdigest()
    refused_hash = hashlib.sha1(wrong.read_bytes()).hexdigest()
    if fault:
        wrong.write_bytes(b"different")
    context = SimpleNamespace(source_dir=tmp_path, artifact="pokecrystal", lock={"outputs": {
        "pokecrystal": {"filename": rom.name},
        "pokecrystal11": {"filename": wrong.name, "sha1": refused_hash}}},
        source_record=lambda: {"rom_sha1": admitted_hash})
    monkeypatch.setattr(gen2_source_data, "load_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(gates, "qualified_identity", lambda name, *args, **kwargs: 1 if name == "crystal_battle" else 2)
    if fault:
        with pytest.raises(RuntimeError, match="Crystal 1.1 ROM differs"):
            duo_module.gen2_preflight(repo=tmp_path, scenario="gen2_admit_wrong_rom")
    else:
        rows = duo_module.gen2_preflight(repo=tmp_path, scenario="gen2_admit_wrong_rom")
        assert rows["a"]["rom"] == rom
        assert rows["b"]["rom"] == wrong
        assert rows["b"]["rom_sha1"] == refused_hash
        assert rows["b"]["expect_admission"] == "refused"


@pytest.mark.parametrize("admitted", (True, False))
def test_gen2_refusal_go_requires_only_admitted_a(monkeypatch, admitted):
    run = object.__new__(DuoRun)
    run.game, run.scenario = "gen2_new", "gen2_admit_wrong_rom"
    run.gcfg, run._lane = GAMES[run.game], "cc"
    run._status = lambda: {"players": {"a": {"connected": True,
        "admission": "admitted" if admitted else "refused"}}}
    monkeypatch.setattr(duo_module, "read_result", lambda scenario, side: "HELLO {}" if side == "a" else "")
    run._gen2_admit_snapshot = lambda: {"baseline": True}
    released = []
    run.go = lambda: released.append(True)
    def wait(label, predicate, timeout):
        if not predicate():
            raise RuntimeError("no admitted hello")
    run.wait_for = wait
    if admitted:
        run.orchestrate()
        assert released == [True]
        assert run._gen2_admit_before == {"baseline": True}
    else:
        with pytest.raises(RuntimeError, match="no admitted hello"):
            run.orchestrate()
        assert not released


@pytest.mark.parametrize("phase", ("same_save", "wrong_save"))
def test_gen2_reconnect_stages_immutable_seeds_and_rebinds_boot_fingerprint(monkeypatch, tmp_path, phase):
    import hashlib
    import json
    from pathlib import Path

    import run_gb_gate as gate

    monkeypatch.setattr(duo_module, "BUILD", str(tmp_path))
    run = object.__new__(DuoRun)
    run.game, run.scenario, run._lane = "gen2_new", "gen2_reconnect", "cc"
    run.cfg = SCENARIOS[run.scenario]
    source = tmp_path / "source.SaveRAM"
    source.write_bytes(b"staged independent save")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    run._gen2_inputs = {"a": {"title": "crystal", "wrong_sha256": digest}}
    old = {"directory": tmp_path / "initial"}
    run._gen2_plans = {"a": old}
    run._gen2_env = {"a": {"SLINK_GEN2_FIXTURE_CASE": json.dumps({"name": "crystal_battle", "attempt_id": "old"}),
                          "SLINK_GEN2_QUALIFY": json.dumps({"stage": "boot", "stage_fingerprint": "old", "facts": {"pin": 1}})}}
    run._gen2_staged_saves, run._gen2_relaunch_saves = {}, {}
    run.go_files = {"a": str(tmp_path / "go")}
    Path(run.go_files["a"]).write_text("A_DONE_SAME")
    run._expected_exit = {"a"}
    launched = []
    run.launch_instance = lambda *args, **kwargs: launched.append((args, kwargs))
    monkeypatch.setitem(gate.GENS["gen2"], "plan", lambda title, directory, seed, speed: {
        "directory": directory, "fixture": seed, "saveram_name": "crystal.SaveRAM"})
    initial_witness = tmp_path / f"e2e_{run.artifact_name}_a_witness.SaveRAM"
    initial_witness.write_bytes(b"initial link witness remains immutable")
    run._stage_gen2_reconnect(phase, source, "abcd:1234:01")
    assert initial_witness.read_bytes() == b"initial link witness remains immutable"
    assert old["directory"] == tmp_path / "initial"
    assert run._gen2_staged_saves[phase] != source
    assert run._gen2_staged_saves[phase].read_bytes() == source.read_bytes()
    assert run._gen2_relaunch_saves[phase].read_bytes() == source.read_bytes()
    assert run._gen2_relaunch_saves[phase].parent.name.endswith("_" + phase)
    assert json.loads(run._gen2_env["a"]["SLINK_GEN2_QUALIFY"]) == {
        "stage": "boot", "stage_fingerprint": digest, "facts": {"pin": 1}}
    assert json.loads(run._gen2_env["a"]["SLINK_GEN2_FIXTURE_CASE"])["attempt_id"] != "old"
    assert Path(run.go_files["a"]).read_text() == ""
    assert launched == [(("a",), {"phase": phase, "seed": False, "expected_key": "abcd:1234:01"})]
    assert not run._expected_exit


def test_gen2_reconnect_cannot_pass_without_all_live_legs():
    run = object.__new__(DuoRun)
    run.scenario = "gen2_reconnect"
    run._live_complete = {}
    assert run._live_ok() is False
    run._live_complete[run.scenario] = True
    assert run._live_ok() is True


def test_gen2_soft_reset_has_required_oracle_and_live_leg():
    assert SCENARIOS["gen2_soft_reset"]["oracle"] == "assert_gen2_soft_reset_saved"
    run = object.__new__(DuoRun)
    run.scenario, run._live_complete = "gen2_soft_reset", {}
    assert not run._live_ok()


def test_gen2_soft_reset_baseline_precedes_chord(monkeypatch, tmp_path):
    from pathlib import Path

    run = object.__new__(DuoRun)
    run.go_files = {"a": str(tmp_path / "go")}
    run._live_complete = {}
    rows = [{"player": "a", "type": "hello", "text": "Connected (A)"},
            {"player": "b", "type": "hello", "text": "Connected (B)"}]
    snapshots = []
    def snapshot():
        snapshots.append(Path(run.go_files["a"] + ".chord").exists())
        return {"events": list(rows)}
    run._gen2_admit_snapshot = snapshot
    run._read_receipt = lambda side: 'HELLO_AT_CHECKPOINT {"hellos":1}\nREHELLO {"hellos":2}'
    def events():
        return [{"player": "a", "type": "hello", "text": "Connected (A)"}] + rows
    run._reconnect_events = events
    def wait(label, predicate, timeout):
        assert predicate(), label
    run.wait_for = wait
    run._orchestrate_gen2_soft_reset()
    assert snapshots == [False, True]
    assert run._live_complete["gen2_soft_reset"]


def test_gen2_reconnect_orchestration_keeps_b_online_and_archives_initial_a(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    monkeypatch.setattr(duo_module, "BUILD", str(tmp_path))
    run = object.__new__(DuoRun)
    run.game, run.scenario, run._lane = "gen2_new", "gen2_reconnect", "cc"
    run._gen2_plans = {"a": {"directory": tmp_path, "saveram_name": "initial.SaveRAM"}}
    run._gen2_inputs = {"a": {"wrong_fixture": tmp_path / "wrong.SaveRAM"}}
    run._live_complete = {}
    state = {"phase": "initial", "connected": True, "b_done": False}
    actions = []
    def text(side):
        if side == "b" and state["b_done"]:
            return "RESULT: PASS B stayed"
        if side == "b" or state["phase"] == "initial":
            return "RECONNECT_READY " + json.dumps({"key": side + "-key"})
        return 'RECONNECT_HELLO {"hellos":1}\nWRONG_SAVE_HUD {"text":"wrong"}\nRESULT: PASS relaunch'
    run._read_receipt = text
    run._status = lambda: {"players": {
        "a": {"connected": state["connected"], "party_keys": ["a-key"],
              "identity_error": "wrong" if state["phase"] == "wrong_save" else ""},
        "b": {"connected": True}}}
    run._links_json = lambda: [{"status": "alive", "area_id": "route_29",
                               "a": {"key": "a-key"}, "b": {"key": "b-key"}}]
    def snapshot():
        row = {"phase": state["phase"], "connected": state["connected"]}
        actions.append(("snapshot", row["phase"], row["connected"]))
        return row
    run._gen2_admit_snapshot = snapshot
    def terminate(side):
        assert side == "a"
        state["connected"] = False
        actions.append(("kill", state["phase"]))
    run.terminate_instance = terminate
    def stage(phase, source, key):
        assert key == "a-key"
        state.update(phase=phase, connected=True)
        actions.append(("stage", phase, Path(source).name))
    run._stage_gen2_reconnect = stage
    def append(side, marker):
        actions.append((side, marker))
        if marker == "B_DONE":
            state["b_done"] = True
    run._append_reconnect_marker = append
    run.emu_by_inst = {"a": SimpleNamespace(wait=lambda **kwargs: None)}
    def wait(label, predicate, timeout):
        result = predicate()
        assert result, label
        return result
    run.wait_for = wait
    run._orchestrate_gen2_reconnect()
    # Capture connected evidence BEFORE permitting client teardown; B stays until every cut.
    assert actions == [("snapshot", "initial", True), ("kill", "initial"),
                       ("snapshot", "initial", False), ("stage", "same_save", "initial.SaveRAM"),
                       ("snapshot", "same_save", True), ("a", "A_DONE_SAME"), ("kill", "same_save"),
                       ("snapshot", "same_save", False), ("stage", "wrong_save", "wrong.SaveRAM"),
                       ("snapshot", "wrong_save", True), ("a", "A_DONE_WRONG"),
                       ("kill", "wrong_save"), ("b", "B_DONE")]
    initial = tmp_path / f"e2e_{run.artifact_name}_a_initial_result.txt"
    assert "RECONNECT_READY" in initial.read_text() and "RESULT:" not in initial.read_text()
    assert "RESULT: PASS" in Path(run._result_path("a")).read_text()
    assert run._live_ok()


def test_gen2_new_selects_link_and_faint_with_required_evidence():
    assert "gen2_new" in GAMES
    assert scenarios_for("gen2_new") == EXPECTED_GEN2_TRADE + EXPECTED_GEN2
    # gen2_ball_gate boots the zero-Ball town fixtures on C-C and G-S only (duo-pairs needs no C-G cell)
    pairs = ("gen2_new", "gen2_gold_silver", "gen2_crystal_gold")
    assert [scenario_applies("gen2_ball_gate", g) for g in pairs] == [True, True, False]
    assert scenario_attempt_limit("gen2_ball_gate", "gen2_new") == 2
    assert duo_module.GEN2_BALL_GATE_FIXTURES == {"gen2_new": {"a": "crystal_town", "b": "crystal_town_ot2"},
                                                  "gen2_gold_silver": {"a": "gold_town", "b": "silver_town"}}
    assert callable(getattr(DuoRun, SCENARIOS["gen2_ball_gate"]["oracle"], None))
    contract = duo_module.evidence_contract("gen2_new")
    assert contract.require_oracle and contract.witness_validator
    assert callable(getattr(DuoRun, contract.witness_validator, None))
    assert callable(getattr(DuoRun, SCENARIOS["link"]["oracle"], None))
    assert SCENARIOS["gen2_faint"]["oracle"] == "assert_gen2_faint_saved"
    assert callable(getattr(DuoRun, SCENARIOS["gen2_faint"]["oracle"], None))
    for game in GAMES:
        assert scenario_applies("link", game) == (GAMES[game].get("game", game) == "gen2_new")
        assert scenario_applies("gen2_faint", game) == (GAMES[game].get("game", game) == "gen2_new")


@pytest.mark.parametrize("game,fixtures", (
    ("gen2_new", {"a": "crystal_battle", "b": "crystal_battle_ot2"}),
    ("gen2_gold_silver", {"a": "gold_battle", "b": "silver_battle"}),
    ("gen2_crystal_gold", {"a": "crystal_battle", "b": "gold_battle"}),
))
def test_gen2_pairing_rows_share_link_contract(game, fixtures):
    assert game in GAMES
    assert GAMES[game]["game"] == "gen2_new"
    assert GAMES[game]["fixture"] == fixtures
    trade = EXPECTED_GEN2_TRADE   # O-34: every pairing, C-G included, runs the native trade
    c_g_only_not = {"gen2_ball_gate", "gen2_faint_active_trainer", *duo_module.GEN2_SYNTH_SCENARIOS}   # C-C, G-S only
    expected = [one for one in EXPECTED_GEN2 if one not in c_g_only_not or game != "gen2_crystal_gold"]
    assert scenarios_for(game) == trade + expected
    assert duo_module.evidence_contract(game) is duo_module.evidence_contract("gen2_new")
    assert not GAMES[game].get("server_rom_routes")
    trade_fixtures = duo_module.GEN2_TRADE_FIXTURES.get(game)
    assert duo_list_lines(game) == [
        f"{scenario}  attempts=1  targets=a:{trade_fixtures['a']}, b:{trade_fixtures['b']} artifact=overlay admission=HARNESS_ONLY_OVERLAY"
        for scenario in trade] + [
        f"{scenario}  attempts={3 if scenario in duo_module.GEN2_CLAUSE_SCENARIOS else 1}  targets="
        f"a:{'gold_battle_errand' if scenario == 'gen2_poison' and game == 'gen2_gold_silver' else fixtures['a']}, "
        f"b:{'crystal_battle_ot2' if scenario == 'gen2_admit_wrong_rom' else fixtures['b']}"
        if scenario not in c_g_only_not else
        f"{scenario}  attempts=2  targets=a:{duo_module.GEN2_BALL_GATE_FIXTURES[game]['a']}, "
        f"b:{duo_module.GEN2_BALL_GATE_FIXTURES[game]['b']}"
        if scenario == "gen2_ball_gate" else
        f"{scenario}  attempts=1  targets=a:{trade_fixtures['a']}, b:{trade_fixtures['b']}"
        if scenario == "gen2_faint_active_trainer" else
        f"{scenario}  attempts=1  targets=a:{duo_module.gen2_synth_name(scenario, game, 'a')}, "
        f"b:{duo_module.gen2_synth_name(scenario, game, 'b')}"
        for scenario in expected]


@pytest.mark.parametrize("game,titles,names", (
    ("gen2_gold_silver", ("gold", "silver"), ("gold_battle", "silver_battle")),
    ("gen2_crystal_gold", ("crystal", "gold"), ("crystal_battle", "gold_battle")),
))
@pytest.mark.parametrize("fault", (None, "rom_a", "rom_b", "same_ot", "same_bytes"))
def test_gen2_pairing_preflight_binds_each_source_and_fixture(
        monkeypatch, tmp_path, game, titles, names, fault):
    import hashlib
    import json
    from types import SimpleNamespace

    from tests.live import test_gen2_new_gates as gates
    from tools import gen2_source_data

    fixture_dir = tmp_path / "tests/fixtures/gen2"
    receipt_dir = fixture_dir / "receipts"
    receipt_dir.mkdir(parents=True)
    contexts, expected, loaded, qualified = {}, {}, [], []
    for index, (side, title, name) in enumerate(zip(("a", "b"), titles, names, strict=True)):
        source_dir = tmp_path / title
        source_dir.mkdir()
        rom = source_dir / f"{title}.gbc"
        rom.write_bytes(title.encode())
        pin = hashlib.sha1(rom.read_bytes()).hexdigest()
        if fault == f"rom_{side}":
            rom.write_bytes(b"wrong ROM")
        contexts[title] = SimpleNamespace(
            source_dir=source_dir, artifact=title,
            lock={"outputs": {title: {"filename": rom.name}}},
            source_record=lambda pin=pin: {"rom_sha1": pin})
        raw = b"same" if fault == "same_bytes" else name.encode()
        fixture = fixture_dir / f"{name}.SaveRAM"
        fixture.write_bytes(raw)
        ot_id = 123 if fault == "same_ot" else 123 + index
        receipt = receipt_dir / f"{name}.qualification.json"
        receipt.write_text(json.dumps({"attempt_id": f"qualified-{side}", "ot_id": ot_id}))
        expected[side] = {"title": title, "name": name, "rom": rom, "rom_sha1": pin,
                          "fixture": fixture, "sha256": hashlib.sha256(raw).hexdigest(),
                          "ot_id": ot_id, "qualification": receipt,
                          "qualification_attempt_id": f"qualified-{side}"}

    def load(title, *, root):
        assert root == tmp_path
        loaded.append(title)
        return contexts[title]

    def identity(name, raw, *, repo):
        assert repo == tmp_path
        assert raw == (fixture_dir / f"{name}.SaveRAM").read_bytes()
        qualified.append(name)
        return json.loads((receipt_dir / f"{name}.qualification.json").read_text())["ot_id"]

    monkeypatch.setattr(gen2_source_data, "load_context", load)
    monkeypatch.setattr(gates, "qualified_identity", identity)
    if fault:
        match = "ROM differs" if fault.startswith("rom_") else "distinct qualified OTs"
        with pytest.raises(RuntimeError, match=match):
            duo_module.gen2_preflight(repo=tmp_path, game=game)
    else:
        assert duo_module.gen2_preflight(repo=tmp_path, game=game) == expected
        assert loaded == list(titles)
        assert qualified == list(names)


def _gen2_wrapper(monkeypatch, tmp_path):
    from types import SimpleNamespace

    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    wrapper = __import__("test_duo_gen2_new")
    monkeypatch.setattr(wrapper, "REPO", tmp_path)
    emulator = tmp_path / "EmuHawk.exe"
    emulator.touch()
    monkeypatch.setattr(wrapper.duo, "EMUHAWK", str(emulator))
    monkeypatch.setattr(wrapper.duo, "gen2_preflight", lambda **kwargs: {}, raising=False)
    monkeypatch.setitem(wrapper.duo.SCENARIOS, "link", {"timeout": 1})
    build = tmp_path / "patch" / "build"
    build.mkdir(parents=True)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    return wrapper, build


@pytest.mark.parametrize("missing", ("rom", "fixture", "qualification receipt"))
@pytest.mark.parametrize("game", ("gen2_new", "gen2_gold_silver", "gen2_crystal_gold"))
@pytest.mark.parametrize("scenario", ("link", "gen2_faint"))
def test_gen2_duo_wrapper_refuses_missing_preflight_input(monkeypatch, tmp_path, missing, game, scenario):
    wrapper, _ = _gen2_wrapper(monkeypatch, tmp_path)

    def refuse(**kwargs):
        raise AssertionError(f"missing {missing}")

    def forbidden(*args, **kwargs):
        pytest.fail("launched despite failed fixture preflight")

    monkeypatch.setattr(wrapper.duo, "gen2_preflight", refuse)
    monkeypatch.setattr(wrapper.subprocess, "run", forbidden)
    with pytest.raises(AssertionError, match=f"missing {missing}"):
        wrapper.run_gate(game, scenario)


def test_gen2_duo_wrapper_cannot_reuse_stale_pass_receipts(monkeypatch, tmp_path):
    wrapper, build = _gen2_wrapper(monkeypatch, tmp_path)
    for side in ("a", "b", "pydec"):
        prefix = "PYDEC" if side == "pydec" else "RESULT"
        (build / f"e2e_link_gen2-cc-link_{side}_result.txt").write_text(f"{prefix}: PASS\n")
    with pytest.raises(AssertionError, match="missing fresh a receipt"):
        wrapper.run_link_gate()


@pytest.mark.parametrize("game,lane", (
    ("gen2_new", "gen2-cc-link"),
    ("gen2_gold_silver", "gen2-gs-link"),
    ("gen2_crystal_gold", "gen2-cg-link"),
))
def test_gen2_duo_wrapper_selects_pairing_for_preflight_and_launch(
        monkeypatch, tmp_path, game, lane):
    from types import SimpleNamespace

    wrapper, build = _gen2_wrapper(monkeypatch, tmp_path)
    checked = []
    monkeypatch.setattr(wrapper.duo, "gen2_preflight", lambda **kw: checked.append(kw))

    def run(cmd, **kwargs):
        assert checked == [{"repo": tmp_path, "game": game, "scenario": "link"}]
        assert cmd[-6:] == ["--game", game, "--scenario", "link", "--lane", lane]
        for side in ("a", "b", "pydec"):
            prefix = "PYDEC" if side == "pydec" else "RESULT"
            (build / f"e2e_link_{lane}_{side}_result.txt").write_text(f"{prefix}: PASS\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    wrapper.run_link_gate(game)


@pytest.mark.parametrize("bad", ("a", "b", "pydec", "none"))
@pytest.mark.parametrize("mode", ("fail", "absent"))
@pytest.mark.parametrize("scenario", ("link", "gen2_faint"))
def test_gen2_duo_wrapper_requires_both_results_and_pydec(monkeypatch, tmp_path, bad, mode, scenario):
    from types import SimpleNamespace

    wrapper, build = _gen2_wrapper(monkeypatch, tmp_path)

    def run(cmd, **kwargs):
        assert cmd[-6:] == ["--game", "gen2_new", "--scenario", scenario,
                            "--lane", "gen2-cc-" + scenario.removeprefix("gen2_")]
        for side in ("a", "b", "pydec"):
            if side == bad and mode == "absent":
                continue
            prefix = "PYDEC" if side == "pydec" else "RESULT"
            verdict = "FAIL" if side == bad else "PASS"
            lane = "gen2-cc-" + scenario.removeprefix("gen2_")
            (build / f"e2e_{scenario}_{lane}_{side}_result.txt").write_text(f"{prefix}: {verdict}\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    if bad == "none":
        wrapper.run_gate(scenario=scenario)
    else:
        match = f"missing fresh {bad} receipt" if mode == "absent" else f"failed {bad} verdict"
        with pytest.raises(AssertionError, match=match):
            wrapper.run_gate(scenario=scenario)


@pytest.mark.parametrize("scenario", ["gen2_faint", "gen2_faint_active"])
def test_gen2_faint_oracle_receives_qualified_inputs_and_requires_witness(monkeypatch, tmp_path, scenario):
    from types import SimpleNamespace

    seen = []
    results = {"a": "A receipt", "b": "B receipt"}
    module = SimpleNamespace(check_save_witness=lambda res: seen.append(("witness", res)),
        faint_oracle=lambda res, **kwargs: seen.append((kwargs, res)),
        faint_active_oracle=lambda res, **kwargs: seen.append((kwargs, res)))
    monkeypatch.setitem(sys.modules, "gen2_duo_oracles", module)
    run = object.__new__(DuoRun)
    run.game, run.scenario = "gen2_gold_silver", scenario
    run.cfg, run.data_dir = SCENARIOS[run.scenario], str(tmp_path)
    run._gen2_inputs = {"a": {"ot_id": 101, "fixture": tmp_path / "gold.SaveRAM"},
                        "b": {"ot_id": 202, "fixture": tmp_path / "silver.SaveRAM"}}
    run._run_oracle(results)
    assert seen == [("witness", results), ({"data_dir": str(tmp_path),
        "on_verified": run._record_gen2_facts,
        "ot_ids": {"a": 101, "b": 202},
        "boot_saveram": {"a": tmp_path / "gold.SaveRAM", "b": tmp_path / "silver.SaveRAM"}}, results)]
    run.check_gen2_save_witness = None
    with pytest.raises(RuntimeError, match="witness validator"):
        run._run_oracle(results)


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "malformed", "partial", "not_active"])
def test_gen2_active_release_requires_one_valid_b_marker(monkeypatch, fault):
    import json
    from types import SimpleNamespace

    row = {"key": "1234:5678:0013", "slot": 1, "cur_battle_mon": 1, "battle_mode": 1, "link_mode": 0}
    if fault == "not_active":
        row["cur_battle_mon"] = 0
    text = "LINKED_ACTIVE " + json.dumps(row) + "\n"
    text = {"missing": "", "duplicate": text + text, "malformed": "LINKED_ACTIVE {bad}\n",
            "partial": "LINKED_ACTIVE {"}.get(fault, text)
    monkeypatch.setattr(duo_module, "read_result", lambda name, side: text if side == "b" else "")
    run = object.__new__(DuoRun)
    run.game, run.scenario = "gen2_new", "gen2_faint_active"
    run.args, run.cfg = SimpleNamespace(lane="cc"), {"timeout": 3000}
    seen = []

    def wait(description, observe, timeout):
        assert timeout == 3000
        seen.append("wait")
        result = observe()
        if result is None:
            raise TimeoutError(description)
        return result

    run.wait_for = wait
    run._go_one = lambda inst, lines: seen.append((inst, lines))
    if fault:
        with pytest.raises((RuntimeError, TimeoutError)):
            run._release_gen2_active_faint()
        assert seen == ["wait"]
    else:
        run._release_gen2_active_faint()
        assert seen == ["wait", ("a", ["B_ACTIVE"])]
        assert run._gen2_active_release == row


@pytest.mark.parametrize("missing", ("driver", "faint_inputs", "witness", "oracle", None))
@pytest.mark.parametrize("scenario", ["gen2_faint", "gen2_faint_active"])
def test_gen2_faint_prelaunch_requires_its_driver_and_oracle(monkeypatch, tmp_path, missing, scenario):
    from types import SimpleNamespace

    emulator = tmp_path / "EmuHawk.exe"
    emulator.touch()
    monkeypatch.setattr(duo_module, "EMUHAWK", str(emulator))
    monkeypatch.setattr(duo_module, "REPO", str(tmp_path))
    monkeypatch.setattr(duo_module, "gen2_preflight", lambda **kwargs: {})
    driver_dir = tmp_path / "lua/tests/duo"
    driver_dir.mkdir(parents=True)
    for name in ("duo_gen2_main.lua", "scenario_gen2_link.lua", "gen2_route29_inputs.lua"):
        (driver_dir / name).touch()
    if missing != "driver":
        (driver_dir / f"scenario_{scenario}.lua").touch()
    if missing != "faint_inputs":
        (driver_dir / "gen2_faint_inputs.lua").touch()
    callbacks = {"link_oracle": lambda results: None,
                  "faint_oracle": lambda results: None,
                  "faint_active_oracle": lambda results: None,
                  "check_save_witness": lambda results: None}
    if missing in ("witness", "oracle"):
        oracle_name = "faint_active_oracle" if scenario == "gen2_faint_active" else "faint_oracle"
        del callbacks["check_save_witness" if missing == "witness" else oracle_name]
    monkeypatch.setitem(sys.modules, "gen2_duo_oracles", SimpleNamespace(**callbacks))
    run = object.__new__(DuoRun)
    run.game, run.scenario = "gen2_new", scenario
    run.gcfg = GAMES[run.game]
    if missing == "driver":
        with pytest.raises(FileNotFoundError, match="scenario_gen2_faint"):
            run._prepare_gen2_lane()
    elif missing == "faint_inputs":
        with pytest.raises(FileNotFoundError, match="gen2_faint_inputs"):
            run._prepare_gen2_lane()
    elif missing:
        with pytest.raises(RuntimeError, match="witness/oracle implementation missing"):
            run._prepare_gen2_lane()
    else:
        run._prepare_gen2_lane()


def test_unknown_family_does_not_inherit_legacy_evidence():
    with pytest.raises(RuntimeError, match="evidence contract"):
        duo_module.evidence_contract("unregistered")

GEN1_NEW_SCENARIOS = ("link_new", "deadzone_new", "linked_faint_bench_new",
                      "linked_faint_active_new", "trade_new", "reconnect_new", "ball_gate_new",
                      "admit_randomized_new", "soft_reset_new", "trade_decline_new",
                      "explode_new", "pc_ops_new", "changebox_new", "whiteout_new",
                      "type_clause_new", "species_clause_new", "poison_new", "rival_swap_new",
                      "linked_faint_bench_battle_new", "explode_bench_battle_new")


@pytest.mark.parametrize("game", sorted(GAMES))
def test_every_game_runs_something(game):
    """A title with an empty selection would report `all passed` having run nothing."""
    assert scenarios_for(game), f"no scenario applies to {game}"


# NOT asserted, and the reason is worth writing down: `faint` and `boxsync` declare
# `"savestate": "slink_overworld.State"` and still run on Gen 1 and Gen 2, which have no
# savestate at all. That is not a contradiction. The launch path branches on the GAME
# (`DuoRun.battery_boot`, from GAMES[game]["uses_savestate"]), so a scenario's savestate is
# Gen 3 data that battery-boot titles never read. The first version of this file asserted the
# tidy-looking invariant instead and failed on three games — the table was right and the test
# was wrong.


@pytest.mark.parametrize("game", sorted(GAMES))
def test_savestate_games_are_never_given_a_batteryless_scenario(game):
    """This direction IS load-bearing: tests/e2e/test_duo.py KeyErrors in `_states_for` on a
    scenario with no savestate, so selecting one for Gen 3 breaks collection of the whole
    module rather than failing a single test."""
    if not GAMES[game]["uses_savestate"]:
        pytest.skip(f"{game} boots from a battery save")
    offenders = [n for n in scenarios_for(game) if "savestate" not in SCENARIOS[n]]
    assert not offenders, (
        f"{game} loads savestates but would be given scenario(s) that declare none: "
        f"{offenders}")


def test_gen3_selection_is_exactly_the_radical_red_set():
    """Pinned rather than derived, so that widening a `games` tuple by accident has to be an
    explicit edit here too. tests/e2e/test_duo.py parametrizes straight off this selection."""
    assert sorted(scenarios_for("gen3_rr")) == sorted(
        ["faint", "boxsync", "trade", "ghost", "infopanel", "explode"])


def test_legacy_gen2_chain_is_not_selectable():
    assert "gen2" not in GAMES
    assert "gen2_crystal" not in duo_module.FAMILY_EVIDENCE
    assert "memorialize" not in SCENARIOS


def test_the_old_gen1_titles_are_gone():
    """Deletion step 3: the `gen1`/`gen1_yellow` titles, their scenario drivers and the family
    rule that covered them are removed, so every `games` tuple is exact."""
    assert "gen1" not in GAMES and "gen1_yellow" not in GAMES
    for name in ("rivalswap", "explode_g1", "whiteout", "playthrough", "deadzone", "dupes"):
        assert name not in SCENARIOS, name
    assert not hasattr(duo_module, "FAMILIES") or not duo_module.FAMILIES


def test_selection_does_not_leak_across_generations():
    """Exact matching: nothing from another title's set may appear."""
    for game in ("gen2_new", "gen2_gold_silver", "gen2_crystal_gold"):
        assert not scenario_applies("trade", game)
        assert not scenario_applies("link_new", game)


def test_the_pytest_wrappers_agree_with_the_runner():
    """The per-generation wrapper hardcodes the scenarios it runs. If it names one the runner
    would refuse for that game, the two have drifted — which is the original bug, just pointing
    the other way."""
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen2_new")
    for game in mod.PAIRINGS:   # the wrapper skips what a pairing does not register (C-G trade, Q10)
        assert set(scenarios_for(game)) <= set(mod.SCENARIOS)
        assert set(mod.SCENARIOS) - set(scenarios_for(game)) <= set(duo_module.GEN2_TRADE_SCENARIOS) | {"gen2_ball_gate", "gen2_faint_active_trainer",
                                                                                                           *duo_module.GEN2_SYNTH_SCENARIOS}
    assert set(mod.SCENARIOS) == set().union(*(scenarios_for(game) for game in mod.PAIRINGS))


def test_every_gen1_new_scenario_declares_an_oracle_that_exists():
    """A client RESULT is not a verdict: each Gen 1 scenario names the post-result method that
    reads the saved state, and the method has to exist on DuoRun."""
    for name in scenarios_for("gen1_new"):
        method = SCENARIOS[name].get("oracle")
        assert method, f"{name} declares no oracle"
        assert callable(getattr(DuoRun, method, None)), f"{name} names {method}, not a DuoRun method"
        assert isinstance(SCENARIOS[name].get("oracle_kwargs", {}), dict)


def test_gen3_keeps_the_legacy_verdict_path():
    """Gen 3 entries retain their existing verdict path."""
    for name in scenarios_for("gen3_rr"):
        assert "oracle" not in SCENARIOS[name], f"{name} declares an oracle"


def test_gen1_new_does_not_inherit_the_old_gen1_family():
    """The family rule exists for gen1_yellow. `gen1_new` is a different client whose driver
    refuses every old scenario name, so `--scenario all --game gen1_new` must select only its
    own eight rather than six scenarios it cannot run."""
    assert sorted(scenarios_for("gen1_new")) == sorted(GEN1_NEW_SCENARIOS)
    assert not scenario_applies("trade", "gen1_new")


def test_the_wrapper_lists_exactly_the_gen1_new_scenarios():
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    assert mod.GAME == "gen1_new"
    assert sorted(mod.SCENARIOS) == sorted(GEN1_NEW_SCENARIOS)


def test_whiteout_new_is_registered_for_gen1_new_and_nothing_else():
    """S-4/W-3's scenario opts in to `gen1_new` alone.

    Both directions matter: an entry that lost its `games` key would match every title the
    family rule does not exclude (the old default), and one written as `("gen1",)` would be
    handed to the gen1 driver, whose scenario table has no `whiteout_new`.
    """
    assert scenario_applies("whiteout_new", "gen1_new")
    assert "whiteout_new" in scenarios_for("gen1_new")
    assert not scenario_applies("whiteout_new", "gen1")
    assert not scenario_applies("whiteout_new", "gen1_yellow")
    assert not scenario_applies("whiteout_new", "gen3_rr")
    assert "whiteout_new" not in scenarios_for("gen2_new")


def test_the_clause_and_poison_scenarios_opt_in_to_gen1_new_alone():
    """A4's two clause scenarios and A7's poison run gen1_new's driver and nothing else: the
    gen1 family's own table has no such names, and neither does another generation's client."""
    for name in ("type_clause_new", "species_clause_new", "poison_new"):
        assert scenario_applies(name, "gen1_new")
        assert name in scenarios_for("gen1_new")
        assert not scenario_applies(name, "gen1")
        assert not scenario_applies(name, "gen1_yellow")
        assert not scenario_applies(name, "gen3_rr")
        assert name not in scenarios_for("gen2_new")


def test_the_clause_and_poison_entries_carry_their_flags_oracles_and_fixtures():
    """--type-clause / --species-clause are what make the server's clause machinery run at all
    (state.py:1750 gates the reroll on species_lock, :2629 on type_lock), and poison_new is the
    per-instance fixture case: A on the town fixture, B on the battle one."""
    assert SCENARIOS["type_clause_new"]["flags"] == ["--type-clause"]
    assert SCENARIOS["species_clause_new"]["flags"] == ["--species-clause"]
    assert SCENARIOS["poison_new"]["flags"] == []
    assert SCENARIOS["poison_new"]["target"] == {"a": "town", "b": "battle"}
    assert SCENARIOS["poison_new"]["timeout"] >= 2400
    assert SCENARIOS["poison_new"]["frames"] >= 300000
    for name, oracle in (("type_clause_new", "assert_type_clause_new_saved"),
                         ("species_clause_new", "assert_species_clause_new_saved"),
                         ("poison_new", "assert_poison_new_saved")):
        entry = SCENARIOS[name]
        assert entry["games"] == ("gen1_new",), name
        assert entry["no_setup"] is True and entry["target"], name
        assert entry["oracle"] == oracle
        assert callable(getattr(DuoRun, oracle, None)), name
    assert callable(getattr(DuoRun, "assert_species_clause_release", None))


def test_rival_swap_new_carries_its_flag_and_the_battle_fixture_on_both_halves():
    """The Route 22 rival events are only armed by the `lab,parcel,route1` chain
    (tools/gen1_fixtures.py:40), so A has to boot the battle fixture — and B too, for its party
    to carry a catch for the swap to mirror."""
    entry = SCENARIOS["rival_swap_new"]
    assert entry["flags"] == ["--rival-team-swap"]
    assert entry["target"] == {"a": "battle", "b": "battle"}
    assert entry["no_setup"] is True and entry["games"] == ("gen1_new",)
    assert entry["oracle"] == "assert_rival_swap_new_saved"
    assert callable(getattr(DuoRun, "assert_rival_swap_new_saved", None))
    assert scenario_applies("rival_swap_new", "gen1_new")
    assert not scenario_applies("rival_swap_new", "gen1")


def test_whiteout_new_carries_the_gen1_new_shape_and_both_of_its_gates():
    """The registry entry plus the two methods the orchestration calls: the pre-blackout
    BOTH_BOXED gate (orchestrate) and the post-result oracle (_run_oracle)."""
    entry = SCENARIOS["whiteout_new"]
    assert entry["games"] == ("gen1_new",)
    assert entry["no_setup"] is True and entry["flags"] == []
    assert entry["target"] == "battle" and entry["timeout"] == 1800
    assert entry["oracle"] == "assert_whiteout_new_saved"
    assert callable(getattr(DuoRun, "assert_whiteout_new_saved", None))
    assert callable(getattr(DuoRun, "assert_whiteout_both_boxed", None))


def test_the_wrapper_deadline_covers_every_attempt():
    """r2 finding 2: species_clause_new may run three whole attempts, so a deadline of one
    timeout would kill the third mid-run — the run would read as a crash, not a long scenario."""
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    for name in scenarios_for("gen1_new"):
        assert mod.deadline_for(name) == (SCENARIOS[name]["timeout"]
                                          * scenario_attempt_limit(name, "gen1_new")) + 300, name
    assert mod.deadline_for("species_clause_new") == (
        scenario_attempt_limit("species_clause_new", "gen1_new")
        * SCENARIOS["species_clause_new"]["timeout"] + 300)


def test_the_wrapper_resolves_fixtures_per_instance_not_as_a_cross_product():
    """r2 finding 3: poison_new boots Red/town and Blue/battle. Checking the cross product
    demanded red_battle and blue_town as well — fixtures the scenario never reads."""
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    assert mod.required_fixtures("poison_new") == [("red", "town"), ("blue", "battle")]
    assert mod.required_fixtures("link_new") == [("red", "battle"), ("blue", "battle")]

    present = {"red_town.SaveRAM", "blue_battle.SaveRAM"}
    exists = lambda path: os.path.basename(path) in present  # noqa: E731
    assert mod.missing_fixtures("poison_new", exists=exists) == []
    present.discard("red_town.SaveRAM")
    assert mod.missing_fixtures("poison_new", exists=exists) == [("red", "town")]
    present.discard("blue_battle.SaveRAM")
    assert len(mod.missing_fixtures("poison_new", exists=exists)) == 2


def test_list_lines_carry_the_attempt_limit_and_the_targets():
    """(r): lane cards quote these two numbers, so --list prints them from the same table the
    runner uses."""
    lines = {line.split()[0]: line for line in duo_list_lines("gen1_new")}
    assert lines["species_clause_new"] == "species_clause_new  attempts=8  targets=battle"
    assert lines["poison_new"] == "poison_new  attempts=4  targets=a:town, b:battle"
    assert lines["rival_swap_new"] == "rival_swap_new  attempts=3  targets=a:battle, b:battle"
    assert lines["ball_gate_new"] == "ball_gate_new  attempts=1  targets=town"
    for name in scenarios_for("gen1_new"):
        assert name in lines, name


@pytest.mark.parametrize("kind", ("type", "gender", "species"))
def test_gen2_clause_registry_requires_observed_oracle(kind):
    name = f"gen2_{kind}_clause"
    row = SCENARIOS[name]
    assert row["flags"] == [f"--{kind}-clause"]
    assert row["oracle"] == "assert_gen2_clause_saved"
    assert row["oracle_kwargs"] == {"kind": kind}
    assert callable(getattr(DuoRun, row["oracle"]))
    for game in ("gen2_new", "gen2_gold_silver", "gen2_crystal_gold"):
        assert name in scenarios_for(game)
        assert scenario_attempt_limit(name, game) == 3
    assert not scenario_applies(name, "gen1_new")


@pytest.mark.parametrize("mismatch", (False, True))
def test_gen2_species_release_records_server_snapshot_before_go(mismatch):
    import json
    run = object.__new__(DuoRun)
    run.cfg = {"timeout": 10}
    marker = {"key": "catch-a", "species_id": 16, "area_id": "route_29"}
    run._read_receipt = lambda inst: "PENDING_CAPTURE " + json.dumps(marker)
    entry = {"key": "catch-a", "species": 19 if mismatch else 16}
    run._status = lambda: {"pending_captures": {"route_29": {"a": entry}}}
    run.wait_for = lambda label, fn, timeout: fn()
    snapshot = {"links": {"pending_captures": {"route_29": {"a": entry}}}, "events": []}
    run._gen2_admit_snapshot = lambda: snapshot
    sent = []
    def go(inst, lines):
        assert run._gen2_clause_pending == snapshot
        sent.append((inst, lines))
    run._go_one = go
    if mismatch:
        with pytest.raises(RuntimeError, match="species"):
            run._release_gen2_species()
        assert not sent
    else:
        run._release_gen2_species()
        assert sent == [("b", ["A_PENDING species=16"])]


@pytest.mark.parametrize("outcomes, expected, attempts", (
    (("unobserved", "pass"), True, 2),
    (("unobserved", "unobserved", "unobserved"), False, 3),
    (("broken", "pass"), False, 1),
))
def test_gen2_clause_retries_only_oracle_validated_unobserved(monkeypatch, outcomes, expected, attempts):
    from types import SimpleNamespace
    class Unobserved(RuntimeError):
        pass
    seen = []
    class FakeRun:
        def __init__(self, name, args, attempt):
            seen.append(attempt)
        def run(self):
            outcome = outcomes[len(seen) - 1]
            if outcome == "unobserved":
                raise Unobserved("valid link without clause")
            if outcome == "broken":
                raise RuntimeError("checksum mismatch")
            return True
    monkeypatch.setattr(duo_module, "DuoRun", FakeRun)
    monkeypatch.setattr(duo_module.importlib, "import_module", lambda name: SimpleNamespace(ClauseUnobserved=Unobserved))
    monkeypatch.setattr(duo_module, "read_result", lambda *args: "RESULT: PASS")
    monkeypatch.setattr(duo_module, "_archive_attempt", lambda *args: None)
    result = duo_module.run_scenario_with_rng_retry("gen2_type_clause", SimpleNamespace(game="gen2_new", idle_jitter=0))
    assert result[:2] == (expected, attempts)
    assert len(seen) == attempts


@pytest.mark.parametrize("extra", ("", "\nRESULT: FAIL (bad checksum)", "\nRESULT: PASS"))
def test_gen2_species_rng_retry_excludes_other_failures(extra):
    rows = {"a": "RESULT: FAIL (the link never formed)",
            "b": "RESULT: FAIL (RNG: the species hunt met only duplicates within its battle budget)" + extra}
    assert duo_module.gen2_species_rng_miss(rows) is (not extra)


@pytest.mark.parametrize("fault, attempts", ((None, 3), ("dead_a", 1), ("failed_a", 1), ("wrong_pending", 1)))
def test_gen2_species_live_early_finish_retries_only_waiting_pending_partner(monkeypatch, fault, attempts):
    import json
    from types import SimpleNamespace
    marker = {"key": "catch-a", "species_id": 16, "area_id": "route_29"}
    receipts = {"a": "PENDING_CAPTURE " + json.dumps(marker),
                "b": "RESULT: FAIL (RNG: the species hunt met only duplicates within its battle budget)"}
    if fault == "failed_a":
        receipts["a"] += "\nRESULT: FAIL (checksum mismatch)"
    runs = []
    def factory(name, args, attempt):
        run = object.__new__(DuoRun)
        run.scenario, run.game, run.args, run.attempt = name, args.game, args, attempt
        run.cfg, run.gcfg = {"timeout": 1}, {}
        run.start_server = run.start_instances = run.orchestrate = lambda: None
        run._read_receipt = receipts.get
        run._process_exited = lambda side: fault == "dead_a" and side == "a"
        run.cleanup = lambda passed: None
        run._gen2_clause_pending = {"links": {"pending_captures": {"route_29": {"a": {
            "key": "other" if fault == "wrong_pending" else "catch-a", "species": 16}}}}}
        runs.append(run)
        return run
    monkeypatch.setattr(duo_module, "DuoRun", factory)
    monkeypatch.setattr(duo_module, "validate_pipeline", lambda *args: None)
    monkeypatch.setattr(duo_module, "read_result", lambda name, side: receipts[side])
    monkeypatch.setattr(duo_module, "_archive_attempt", lambda *args: None)
    result = duo_module.run_scenario_with_rng_retry("gen2_species_clause", SimpleNamespace(game="gen2_new", idle_jitter=0))
    assert result[:2] == (False, attempts)
    assert len(runs) == attempts


@pytest.mark.parametrize(("scenario", "oracle", "key"), [
    ("gen2_whiteout", "whiteout_oracle", "repair"), ("gen2_pc_ops", "pc_ops_oracle", "release"),
    ("gen2_changebox", "changebox_oracle", "box_change"), ("gen2_poison", "poison_oracle", "death"),
    ("gen2_whiteout_rebuild", "whiteout_rebuild_oracle", "rebuild")])
def test_wave_c_scenarios_bind_their_own_saved_state_oracle(monkeypatch, scenario, oracle, key):
    """DUO-WAVE-C contract: the faint body, each scenario's own oracle, faint-shaped kwargs."""
    from types import SimpleNamespace
    row = SCENARIOS[scenario]
    assert row["oracle"] == f"assert_{scenario}_saved" and callable(getattr(DuoRun, row["oracle"]))
    assert duo_module.GEN2_WAVE_C[scenario] == (oracle, key)
    seen = []
    monkeypatch.setitem(sys.modules, "gen2_duo_oracles",
                        SimpleNamespace(**{oracle: lambda results, **kw: seen.append((results, kw)) or "ok"}))
    run = object.__new__(DuoRun)
    run.scenario, run.data_dir = scenario, "data"
    run._gen2_inputs = {side: {"ot_id": n, "fixture": f"{side}.SaveRAM"} for n, side in enumerate("ab")}
    assert getattr(run, row["oracle"])({"a": "A", "b": "B"}) == "ok"
    results, kw = seen[0]
    assert kw["data_dir"] == "data" and kw["ot_ids"] == {"a": 0, "b": 1}
    assert kw["boot_saveram"] == {"a": "a.SaveRAM", "b": "b.SaveRAM"} and callable(kw["on_verified"])


def test_gold_poison_a_plays_the_post_errand_save():
    assert duo_module.GEN2_POISON_FIXTURES == {"gen2_gold_silver": {"a": "gold_battle_errand"}}
    line = next(one for one in duo_list_lines("gen2_gold_silver") if one.startswith("gen2_poison "))
    assert "a:gold_battle_errand, b:silver_battle" in line


def test_bizhawk_path_guard_refuses_a_save_path_near_max_path(tmp_path):
    """A 255-char SaveRAM path was never written by BizHawk (silent); the lane refuses at 240 before any launch."""
    from types import SimpleNamespace
    assert duo_module.bizhawk_path_problem(["C:/x/" + "a" * 200]) is None
    long = "C:/x/" + "a" * 250
    assert duo_module.bizhawk_path_problem(["C:/x/short", long]) == os.path.abspath(long)
    run = object.__new__(DuoRun)
    run._gen2_plans = {"a": {"directory": "C:/x", "saveram_name": "s.SaveRAM"}}
    run._result_path = lambda inst: "C:/x/e2e_gen2_changebox_a_result.txt"
    run._check_bizhawk_paths()   # short: fine
    run._gen2_plans["a"]["directory"] = "C:/" + "d" * 240
    with pytest.raises(RuntimeError, match="path too long for BizHawk"):
        run._check_bizhawk_paths()
