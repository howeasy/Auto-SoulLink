"""F-4 runner orchestration with fake UPR outputs and server receipts; no jar or emulator."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from lupa import LuaRuntime

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402
from run_gb_gate import GENS  # noqa: E402

from server import upr_pipeline  # noqa: E402
from server.adapters import (  # noqa: E402
    gen1_codec as codec,
    gen1_rom_scan as scan,
)
from server.upr_settings import build_categories  # noqa: E402


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(duo, "BUILD", str(tmp_path / "build"))
    source_dir = tmp_path / "patch" / "build"
    source_dir.mkdir(parents=True)
    (source_dir / "gen1_red.gb").write_bytes(b"clean-red")
    (source_dir / "gen1_blue.gb").write_bytes(b"clean-blue")
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "admit_randomized_new"
    run.cfg = dict(duo.SCENARIOS[run.scenario])
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path / "run")
    Path(run.data_dir).mkdir()
    run._saveram_dir = lambda inst: str(tmp_path / f"saves_{inst}")
    return run


def _fake_pipeline(monkeypatch):
    called = []
    monkeypatch.setattr(upr_pipeline, "find_upr_jar", lambda: "fake.jar")
    mapping = {b"random-red": "a" * 64, b"random-blue": "b" * 64,
               b"clean-blue": "c" * 64, b"clean-red": "d" * 64}
    monkeypatch.setattr(scan, "fingerprint_rom", lambda raw: mapping[raw])

    def prepare(jar, settings, sources, out_dir):
        called.append((jar, settings, sources, out_dir))
        Path(out_dir).mkdir(parents=True)
        players = {}
        for player, raw in (("a", b"random-red"), ("b", b"random-blue")):
            output = Path(out_dir) / f"{player}_randomized.gbc"
            output.write_bytes(raw)
            players[player] = {"output": str(output), "fingerprint": mapping[raw],
                               "seed": 1 if player == "a" else 2,
                               "sha1": hashlib.sha1(raw).hexdigest()}
        return {"upr_version": "4.6.1", "settings_sha256": "f" * 64,
                "categories": ["wild"], "spec": {"wild": "random"}, "players": players}

    monkeypatch.setattr(upr_pipeline, "prepare_pair", prepare)
    return called


def test_contract_and_staged_rom_are_ready_before_server(runner, monkeypatch):
    called = _fake_pipeline(monkeypatch)
    contract = runner.prepare_admit_randomized_new()
    assert len(called) == 1
    jar, settings, sources, out_dir = called[0]
    assert jar == "fake.jar"
    assert Path(settings).read_bytes() == build_categories({"wild"})
    assert sources == {p: os.path.join(duo.REPO, runner.gcfg["rom"][p]) for p in ("a", "b")}
    assert out_dir == os.path.join(runner.data_dir, "roms")
    path = Path(runner.data_dir) / "rom_contract.json"
    assert json.loads(path.read_text(encoding="utf-8")) == contract
    assert set(contract) == {"upr_version", "settings_sha256", "categories", "players"}
    assert set(contract["players"]["a"]) == {"fingerprint", "seed", "rom_sha1"}
    assert contract["players"]["a"]["seed"] == "1"
    staged = Path(duo.REPO) / runner._admit_roms["a"]
    assert staged.suffix == ".gb" and staged.read_bytes() == b"random-red"
    assert runner._admit_roms["b"] == runner.gcfg["rom"]["b"]
    assert runner._admit_extra_saves == {"a": "slink red randomized.SaveRAM"}
    assert runner._admit_fingerprints == {"expected_b": "b" * 64, "reported_b": "c" * 64}


def test_missing_jar_fails_before_any_contract_is_written(runner, monkeypatch):
    monkeypatch.setattr(upr_pipeline, "find_upr_jar", lambda: None)
    with pytest.raises(RuntimeError, match="PokeRandoZX.jar missing"):
        runner.prepare_admit_randomized_new()
    assert not (Path(runner.data_dir) / "rom_contract.json").exists()


def test_randomized_save_seeds_base_and_fallback_names(runner, monkeypatch):
    runner._admit_extra_saves = {"a": GENS["gen1"]["patched"]["red_rand_patched"][2]}

    def seed(rom, target, dest_dir):
        assert target == "town"
        path = Path(dest_dir) / GENS["gen1"]["saveram_names"][rom]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{rom}-town".encode())
        return str(path)

    monkeypatch.setattr("run_gb_gate.seed_saveram", seed)
    runner._seed_instance_save("a")
    runner._seed_instance_save("b")
    a_dir = Path(runner._saveram_dir("a"))
    b_dir = Path(runner._saveram_dir("b"))
    assert (a_dir / GENS["gen1"]["saveram_names"]["red"]).read_bytes() == b"red-town"
    assert (a_dir / "slink red randomized.SaveRAM").read_bytes() == b"red-town"
    assert (b_dir / GENS["gen1"]["saveram_names"]["blue"]).read_bytes() == b"blue-town"
    assert len(list(b_dir.iterdir())) == 1


def _receipts(runner, *, b_reason=None, b_party=None):
    got, want = "c" * 64, "b" * 64
    reason = b_reason or ("this is not the cartridge built for player b "
                          f"(reported {got[:12]}, expected {want[:12]})")
    runner._admit_fingerprints = {"reported_b": got, "expected_b": want}
    runner._status = lambda: {"players": {
        "a": {"admission": "admitted", "admission_reason": "cartridge matches the contract",
              "party_keys": ["AAAA:BBBB:99"], "trainer_name": "RED"},
        "b": {"admission": "rejected", "admission_reason": reason,
              "party_keys": b_party or [], "trainer_name": "", "current_area_id": ""}}}
    Path(duo.BUILD).mkdir(parents=True, exist_ok=True)
    for player, variant in (("a", "red"), ("b", "blue")):
        (Path(duo.BUILD) / f"e2e_admit_randomized_new_{player}_result.txt").write_text(
            f"ADMIT_MAP 40 5 6\nADMIT_PARTY 1\nHELLO_RECEIPT {variant} 57 wild_maps\n",
            encoding="utf-8")
    (Path(runner.data_dir) / "events.json").write_text(json.dumps([
        {"player": "a", "type": "hello", "text": "Connected (Red, 1 mons)"},
        {"player": "b", "type": "hello", "text": "REJECTED — " + reason},
    ]), encoding="utf-8")
    (Path(runner.data_dir) / "slink.log").write_text(
        "[a] admission: admitted — cartridge matches the contract\n"
        "[b] admission: rejected — " + reason + "\n", encoding="utf-8")


def test_both_public_admission_verdicts_and_events(runner):
    _receipts(runner)
    runner.assert_admit_randomized_new()


def test_rejected_control_must_name_both_fingerprint_prefixes(runner):
    _receipts(runner, b_reason="not the cartridge built for player b")
    with pytest.raises(RuntimeError, match="fingerprint prefixes"):
        runner.assert_admit_randomized_new()


def test_rejected_control_must_not_adopt_party(runner):
    _receipts(runner, b_party=["DEAD:BEEF:01"])
    with pytest.raises(RuntimeError, match="adopted party"):
        runner.assert_admit_randomized_new()


def test_admission_prestep_runs_before_server_start(runner):
    order = []
    runner.prepare_admit_randomized_new = lambda: order.append("contract")
    runner.start_server = lambda: order.append("server")
    runner.start_instances = lambda: order.append("emulators")
    runner.orchestrate = lambda: order.append("verdicts")
    runner.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    runner.cleanup = lambda passed: order.append(f"cleanup:{passed}")
    runner.args = type("Args", (), {"keep_alive": False})()
    assert runner.run() is True
    assert order == ["contract", "server", "emulators", "verdicts", "cleanup:True"]


def test_python_oracle_receipt_persists_facts_and_terminal_result(runner, tmp_path):
    runner._pydec_path = str(tmp_path / "e2e_admit_randomized_new_pydec_result.txt")
    runner.attempt = 1
    runner.prepare_admit_randomized_new = lambda: None
    runner.start_server = lambda: None
    runner.start_instances = lambda: None
    runner.orchestrate = lambda: runner._pydec_note("public admission fact valid")
    runner.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    runner.cleanup = lambda passed: None
    runner.args = type("Args", (), {"keep_alive": False})()
    assert runner.run() is True
    assert Path(runner._pydec_path).read_text(encoding="utf-8").splitlines() == [
        "attempt 1 of 2", "public admission fact valid", "PYDEC: PASS asserted scenario facts"]


def test_python_oracle_receipt_ends_fail_on_an_assertion_error(runner, tmp_path):
    runner._pydec_path = str(tmp_path / "e2e_admit_randomized_new_pydec_result.txt")
    runner.attempt = 1
    runner.prepare_admit_randomized_new = lambda: None
    runner.start_server = lambda: None
    runner.start_instances = lambda: None
    runner.orchestrate = lambda: (_ for _ in ()).throw(RuntimeError("bad checksum"))
    runner.cleanup = lambda passed: None
    with pytest.raises(RuntimeError, match="bad checksum"):
        runner.run()
    assert Path(runner._pydec_path).read_text(encoding="utf-8").splitlines()[-1] == (
        "PYDEC: FAIL bad checksum")


def _reconnect_snapshots():
    link = {"area_id": "route_1", "status": "alive",
            "a": {"key": "AAAA:1111:01"}, "b": {"key": "BBBB:2222:02"}}
    before = {"links": [link], "player_identity": {"a": {"ot_id": "1234"}}}
    after = {**before, "status": {"players": {
        "a": {"connected": True, "identity_error": "", "party_keys": ["AAAA:1111:01"]},
        "b": {"connected": True}}}}
    events = [{"player": "a", "type": "hello", "text": "Connected (Red, 2 mons)"},
              {"player": "b", "type": "hello", "text": "Connected (Blue, 2 mons)"},
              {"player": "a", "type": "capture", "text": "caught"},
              {"player": "b", "type": "linked", "text": "linked"}]
    return before, after, events


def test_same_save_reconnect_keeps_identity_link_and_event_counts():
    before, after, events = _reconnect_snapshots()
    resumed = events + [{"player": "a", "type": "hello", "text": "Connected (Red, 2 mons)"}]
    assert duo.reconnect_same_problems(before, after, events, resumed, "AAAA:1111:01", "1234") == []
    duplicated = resumed + [{"player": "a", "type": "capture", "text": "duplicate"}]
    assert any("duplicated" in p for p in duo.reconnect_same_problems(
        before, after, events, duplicated, "AAAA:1111:01", "1234"))
    mutated = {**after, "links": []}
    assert any("link changed" in p for p in duo.reconnect_same_problems(
        before, mutated, events, resumed, "AAAA:1111:01", "1234"))


def test_wrong_save_reconnect_only_adds_a_rejected_hello():
    _before, _after, events = _reconnect_snapshots()
    rejected = events + [{"player": "a", "type": "hello", "text": "REJECTED — wrong save/slot"}]
    status = {"players": {"a": {"identity_error": "Identity mismatch for slot A: wrong OT"},
                          "b": {"connected": True}}}
    assert duo.reconnect_wrong_problems(b"unchanged", b"unchanged", status, events, rejected) == []
    assert any("bytes changed" in p for p in duo.reconnect_wrong_problems(
        b"before", b"after", status, events, rejected))
    assert any("gameplay event" in p for p in duo.reconnect_wrong_problems(
        b"same", b"same", status, events,
        rejected + [{"player": "a", "type": "no_catch", "text": "bad"}]))


def test_missing_second_ot_red_save_is_named_and_nonpassing(runner, tmp_path):
    runner._pydec_path = str(tmp_path / "reconnect_pydec.txt")
    runner._wrong_save_missing()
    assert runner._reconnect_complete is False
    assert "WRONG_SAVE_LEG NOT RUN" in Path(runner._pydec_path).read_text(encoding="utf-8")


def test_reconnect_cannot_pass_on_two_client_passes_when_wrong_save_leg_was_not_run(runner):
    runner.scenario = "reconnect_new"
    runner.game = "gen1_new"
    runner.start_server = lambda: None
    runner.start_instances = lambda: None
    runner.orchestrate = lambda: setattr(runner, "_reconnect_complete", False)
    runner.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    runner.cleanup = lambda passed: None
    runner.args = type("Args", (), {"keep_alive": False})()
    assert runner.run() is False


def test_a_only_relaunch_does_not_reseed_the_flushed_save(runner, tmp_path, monkeypatch):
    runner.scenario = "reconnect_new"
    runner.cfg = duo.SCENARIOS[runner.scenario]
    runner.battery_boot = True
    runner.tcp_port = 1234
    runner.attempt = 1
    runner.go_files = {"a": str(tmp_path / "a.go"), "b": str(tmp_path / "b.go")}
    runner.emus, runner.emu_by_inst = [], {}
    Path(duo.BUILD).mkdir()
    runner._seed_instance_save = lambda _inst: pytest.fail("relaunch reseeded SaveRAM")
    monkeypatch.setattr("gen1_playthrough.write_run_config", lambda *_args, **_kw: None)

    class FakeProcess:
        pid = 42

    monkeypatch.setattr(duo.subprocess, "Popen", lambda *_args, **_kw: FakeProcess())
    runner.launch_instance("a", phase="same_save", seed=False, expected_key="AAAA:1111:01")
    stub = (Path(duo.BUILD) / "duo_a.lua").read_text(encoding="utf-8")
    assert 'phase = "same_save"' in stub and 'expected_key = "AAAA:1111:01"' in stub
    assert runner.emu_by_inst["a"].pid == 42 and len(runner.emus) == 1


def test_reconnect_kills_only_a_and_leaves_b_process_running(runner, monkeypatch):
    calls = []

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

        def wait(self, timeout):
            calls.append(("wait", self.pid, timeout))

    runner.emu_by_inst = {"a": Process(41), "b": Process(42)}
    monkeypatch.setattr(duo.subprocess, "run", lambda cmd, **_kwargs: calls.append(tuple(cmd)))
    runner.terminate_instance("a")
    assert calls == [("taskkill", "/PID", "41", "/T", "/F"), ("wait", 41, 15)]


def test_existing_red_town_is_not_a_second_ot_save():
    town = REPO / "tests/fixtures/gen1/red_town.SaveRAM"
    battle = REPO / "tests/fixtures/gen1/red_battle.SaveRAM"
    if not town.exists() or not battle.exists() or not (REPO / "patch/build/gen1_red.gb").exists():
        pytest.skip("Red town/battle saves or clean ROM absent")
    profile = json.loads((REPO / "data/games/gen1_rby/profile.json").read_text(
        encoding="utf-8"))["titles"]["red"]["ram"]
    offset = codec.SRAM_LAYOUT["sMainData"] + profile["wPlayerID"] - profile["wMainDataStart"]
    old_ot = int.from_bytes(battle.read_bytes()[offset:offset + 2], "big")
    assert int.from_bytes(town.read_bytes()[offset:offset + 2], "big") == old_ot
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg = duo.GAMES["gen1_new"]
    with pytest.raises(RuntimeError, match="original OT"):
        run._wrong_red_save_ot(str(town), old_ot)


@pytest.mark.parametrize(
    ("a", "b", "attempt", "expected"),
    [
        ("RESULT: PASS (caught)", duo.RNG_OUT_OF_BALLS, 1, True),
        (duo.RNG_OUT_OF_BALLS, duo.RNG_OUT_OF_BALLS, 1, True),
        ("RESULT: FAIL (linked capture was not returned)",
         "RESULT: FAIL (link_new prerequisite failed: hunt ended out-of-balls)", 1, True),
        ("RESULT: FAIL (linked capture was not returned to party)",
         "RESULT: FAIL (link_new prerequisite failed: hunt ended out-of-balls)", 1, True),
        ("RESULT: FAIL (linked capture was not returned)",
         "RESULT: FAIL (force_faint never arrived)", 1, False),
        ("RESULT: FAIL (force_faint never arrived)", duo.RNG_OUT_OF_BALLS, 1, False),
        ("RESULT: FAIL (linked capture was not returned)", "RESULT: PASS (caught)", 1, False),
        ("RESULT: PASS (caught)", "RESULT: FAIL (timeout)", 1, False),
        (duo.RNG_OUT_OF_BALLS, "RESULT: FAIL (timeout)", 1, False),
        ("RESULT: PASS (caught)", duo.RNG_OUT_OF_BALLS, 2, False),
        ("RESULT: FAIL (linked capture was not returned)",
         "RESULT: FAIL (link_new prerequisite failed: hunt ended out-of-balls)", 2, False),
    ],
)
def test_rng_retry_predicate_accepts_only_the_game_ball_miss(a, b, attempt, expected):
    assert duo.retryable_gen1_rng("gen1_new", {"a": a, "b": b}, attempt) is expected
    assert duo.retryable_gen1_rng("gen1", {"a": a, "b": b}, attempt) is False


@pytest.mark.parametrize(("line", "classification"), [
    ("RESULT: FAIL (hunt ended out-of-balls)", "CAUSE_RNG"),
    ("RESULT: FAIL (link_new prerequisite failed: hunt ended out-of-balls)", "CAUSE_RNG"),
    ("RESULT: FAIL (linked capture was not returned)", "CONSEQUENCE"),
    ("RESULT: FAIL (linked capture was not returned to party)", "CONSEQUENCE"),
    ("RESULT: FAIL (force_faint never arrived)", "FINAL"),
    ("RESULT: FAIL (B could not hold its linked mon active: out-of-balls)", "FINAL"),
    ("RESULT: FAIL (link_new prerequisite failed: hunt ended stuck)", "FINAL"),
])
def test_gen1_result_reason_table_is_exact(line, classification):
    assert duo.classify_gen1_result(line) == classification


@pytest.mark.parametrize(("outcomes", "expected_attempts", "passed"), [
    ([(False, "RESULT: PASS (caught)", duo.RNG_OUT_OF_BALLS),
      (True, "RESULT: PASS (caught)", "RESULT: PASS (caught)")], 2, True),
    ([(False, "RESULT: PASS (caught)", "RESULT: FAIL (timeout)")], 1, False),
    ([(False, duo.RNG_OUT_OF_BALLS, duo.RNG_OUT_OF_BALLS),
      (False, duo.RNG_OUT_OF_BALLS, duo.RNG_OUT_OF_BALLS)], 2, False),
])
def test_rng_retry_restarts_a_whole_run_once_with_labeled_receipts(
    tmp_path, monkeypatch, outcomes, expected_attempts, passed,
):
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    built = []
    active = {"attempt": 0}

    class FakeRun:
        def __init__(self, name, args, attempt):
            built.append((name, attempt, object()))  # every attempt is a distinct run
            active["attempt"] = attempt

        def run(self):
            return outcomes[active["attempt"] - 1][0]

    monkeypatch.setattr(duo, "DuoRun", FakeRun)
    monkeypatch.setattr(duo, "read_result", lambda _name, inst: outcomes[active["attempt"] - 1][
        1 if inst == "a" else 2])
    args = type("Args", (), {"game": "gen1_new"})()
    assert duo.run_scenario_with_rng_retry("link_new", args) == (passed, expected_attempts)
    assert [attempt for _, attempt, _ in built] == list(range(1, expected_attempts + 1))
    assert len({id(run) for _, _, run in built}) == expected_attempts
    for attempt in range(1, expected_attempts + 1):
        for inst in ("a", "b"):
            assert (tmp_path / f"e2e_link_new_{inst}_attempt{attempt}_result.txt").exists()


@pytest.mark.parametrize(("other", "raises"), [
    ("RESULT: PASS (caught)", False),
    ("RESULT: FAIL (unrelated)", True),
])
def test_early_orchestration_rng_miss_exits_without_waiting_for_both_catches(runner, other, raises):
    runner.scenario = "link_new"
    runner.game = "gen1_new"
    runner.attempt = 1
    runner.start_server = lambda: None
    runner.start_instances = lambda: None
    runner.orchestrate = lambda: (_ for _ in ()).throw(duo.GameRngMiss("sole ball missed"))
    runner.wait_results = lambda: (other, duo.RNG_OUT_OF_BALLS)
    runner.cleanup = lambda passed: None
    runner.args = type("Args", (), {"keep_alive": False})()
    if raises:
        with pytest.raises(duo.GameRngMiss):
            runner.run()
    else:
        assert runner.run() is False


def _fixture_save(title):
    path = REPO / "tests" / "fixtures" / "gen1" / f"{title}_battle.SaveRAM"
    rom_path = REPO / "patch" / "build" / f"gen1_{title}.gb"
    if not path.exists() or not rom_path.exists():
        pytest.skip(f"{title} battle fixture or clean dump absent")
    return bytearray(path.read_bytes()), rom_path.read_bytes()


def _new_mon_from_starter(sram, rom):
    start = codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["mons"]
    blob = bytearray(sram[start:start + codec.PARTY_MON_SIZE])
    old_dv = int.from_bytes(blob[27:29], "big")
    blob[27:29] = (old_dv ^ 0x0010).to_bytes(2, "big")
    mon = codec.decode_party_mon(blob)
    base = scan.scan_base_stats(rom)[codec.internal_to_natdex(mon["species"])]
    stats = codec.recompute_stats(mon, base)
    blob[1:3] = stats["max_hp"].to_bytes(2, "big")
    for index, name in enumerate(("max_hp", "atk", "def", "spd", "spc")):
        blob[34 + index * 2:36 + index * 2] = stats[name].to_bytes(2, "big")
    return bytes(blob)


def _seal_main(sram):
    start = codec.SRAM_LAYOUT["sPlayerName"]
    end = codec.SRAM_LAYOUT["sMainDataCheckSum"]
    sram[end] = codec.sav_checksum(sram[start:end])


def _add_caught_to_party(sram, rom):
    blob = _new_mon_from_starter(sram, rom)
    start = codec.SRAM_LAYOUT["sPartyData"]
    layout = codec.PARTY_LAYOUT
    sram[start] = 2
    sram[start + layout["species"] + 1] = blob[0]
    sram[start + layout["species"] + 2] = codec.SPECIES_END
    mon2 = start + layout["mons"] + codec.PARTY_MON_SIZE
    sram[mon2:mon2 + codec.PARTY_MON_SIZE] = blob
    for field in ("ot_names", "nicknames"):
        one = start + layout[field]
        sram[one + codec.NAME_SIZE:one + 2 * codec.NAME_SIZE] = sram[one:one + codec.NAME_SIZE]
    _seal_main(sram)
    return codec.key(codec.decode_party_mon(blob))


def _put_fainted_in_box12(sram, rom):
    blob = bytearray(_new_mon_from_starter(sram, rom))
    blob[1:3] = b"\x00\x00"
    layout = codec.BOX_LAYOUT
    for info in codec.verify_boxes(sram)["boxes"].values():
        start = info["offset"]
        sram[start:start + codec.BOX_SIZE] = bytes(codec.BOX_SIZE)
        sram[start + layout["species"]] = codec.SPECIES_END
    start = codec.verify_boxes(sram)["boxes"][12]["offset"]
    sram[start] = 1
    sram[start + layout["species"]] = blob[0]
    sram[start + layout["species"] + 1] = codec.SPECIES_END
    sram[start + layout["mons"]:start + layout["mons"] + codec.BOX_MON_SIZE] = blob[:codec.BOX_MON_SIZE]
    party_start = codec.SRAM_LAYOUT["sPartyData"]
    for field in ("ot_names", "nicknames"):
        source = party_start + codec.PARTY_LAYOUT[field]
        target = start + layout[field]
        sram[target:target + codec.NAME_SIZE] = sram[source:source + codec.NAME_SIZE]
    sram[codec._CURRENT_BOX] |= codec._BOX_INITIALIZED
    for bank_index, bank_start in enumerate(codec.SRAM_LAYOUT["box_banks"]):
        for slot in range(6):
            box_start = bank_start + slot * codec.BOX_SIZE
            sram[codec.SRAM_LAYOUT["individual_checksums"][bank_index] + slot] = (
                codec.sav_checksum(sram[box_start:box_start + codec.BOX_SIZE]))
        end = codec.SRAM_LAYOUT["all_boxes_checksums"][bank_index]
        sram[end] = codec.sav_checksum(sram[bank_start:end])
    _seal_main(sram)
    return codec.key(codec.decode_party_mon(blob))


def _oracle_runner(tmp_path, scenario):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = scenario
    run.cfg = duo.SCENARIOS[scenario]
    run.gcfg = duo.GAMES["gen1_new"]
    run._saveram_dir = lambda inst: str(tmp_path / f"save_{inst}")

    class Finished:
        def wait(self, timeout):
            assert timeout == 30

    run.emus = [Finished(), Finished()]
    paths = {}
    for inst, title in (("a", "red"), ("b", "blue")):
        sram, rom = _fixture_save(title)
        path = Path(run._saveram_dir(inst)) / GENS["gen1"]["saveram_names"][title]
        path.parent.mkdir(parents=True)
        paths[inst] = (path, sram, rom)
        start = codec.SRAM_LAYOUT["sPartyData"]
        run._boot_keys = getattr(run, "_boot_keys", {})
        run._boot_keys[inst] = codec.key(codec.decode_party(
            sram[start:start + codec.PARTY_LAYOUT["size"]])[0])
    return run, paths


def test_synthetic_link_saved_oracle_passes_and_rejects_a_torn_checksum(tmp_path, capsys):
    run, paths = _oracle_runner(tmp_path, "link_new")
    run._link_keys = {}
    for inst, (path, sram, rom) in paths.items():
        run._link_keys[inst] = _add_caught_to_party(sram, rom)
        path.write_bytes(sram)
    run.assert_link_new_saved()
    assert "saved slot 1 linked" in capsys.readouterr().out
    path, sram, _rom = paths["a"]
    sram[codec.SRAM_LAYOUT["sMainDataCheckSum"]] ^= 1
    path.write_bytes(sram)
    with pytest.raises(RuntimeError, match="saved game would not qualify"):
        run.assert_link_new_saved()
    print("synthetic link_new: PASS; torn main checksum: FAIL")


def test_synthetic_deadzone_saved_oracle_passes_and_rejects_uninitialized_box(tmp_path, capsys):
    run, paths = _oracle_runner(tmp_path, "deadzone_new")
    a_path, a_sram, _a_rom = paths["a"]
    a_path.write_bytes(a_sram)
    b_path, b_sram, b_rom = paths["b"]
    run._deadzone_b_key = _put_fainted_in_box12(b_sram, b_rom)
    b_path.write_bytes(b_sram)
    run.assert_dead_zone_new_saved()
    assert "B Box 12 holds" in capsys.readouterr().out
    b_sram[codec._CURRENT_BOX] &= ~codec._BOX_INITIALIZED
    _seal_main(b_sram)
    b_path.write_bytes(b_sram)
    with pytest.raises(RuntimeError, match="initialized flag invalid"):
        run.assert_dead_zone_new_saved()
    print("synthetic deadzone_new: PASS; cleared saved initialization flag: FAIL")


def _linked_faint_fixture(tmp_path, scenario):
    run, paths = _oracle_runner(tmp_path, scenario)
    run.data_dir = str(tmp_path)
    run._link_keys = {}
    for inst, (path, sram, rom) in paths.items():
        run._link_keys[inst] = _put_fainted_in_box12(sram, rom)
        path.write_bytes(sram)
    (tmp_path / "links.json").write_text(json.dumps({"links": [{
        "area_id": "route_1", "status": "memorial", "cause": "battle",
        "a": {"key": run._link_keys["a"]}, "b": {"key": run._link_keys["b"]},
    }]}), encoding="utf-8")
    (tmp_path / "slink.log").write_text(
        f"[a] faint → force_faint b:{run._link_keys['b']}\n"
        "pair in route_1 fully memorialized\n", encoding="utf-8")
    a_text = (f'BATTLE_FAINT_SITE {run._link_keys["a"]} slot=1 battle_hp=0\n'
              f'TX {{"event":"faint","key":"{run._link_keys["a"]}","player":"a"}}\n'
              f'RX memorialize key={run._link_keys["a"]}\n'
              'TX {"event":"memorialize_done"}\n')
    b_text = (f'RX force_faint key={run._link_keys["b"]}\n'
              f'RX memorialize key={run._link_keys["b"]}\n'
              'GAME_OVER RX game_over\n'
              'TX {"event":"memorialize_done"}\n')
    return run, paths, a_text, b_text


def test_synthetic_bench_faint_oracle_passes_then_rejects_status_corruption(tmp_path, capsys):
    run, paths, a_text, b_text = _linked_faint_fixture(tmp_path, "linked_faint_bench_new")
    results = {"a": a_text,
               "b": b_text + "READY_BENCH map=12 x=8 y=31\nBENCH_HP_STATUS 0000 00\nTILEMAP_FNT row=2\n"}
    run.assert_linked_faint_saved(results, active=False)
    assert "Box 12" in capsys.readouterr().out
    fast_memorial = {"a": a_text, "b": b_text + "READY_BENCH map=12 x=8 y=31\n"
                     "BENCH_HP_STATUS 0000 00\n"
                     "TILEMAP_FNT unavailable: memorialised within 1 frames of the faint\n"}
    run.assert_linked_faint_saved(fast_memorial, active=False)
    path, sram, _rom = paths["b"]
    box = codec.verify_boxes(sram)["boxes"][12]["offset"]
    sram[box + codec.BOX_LAYOUT["mons"] + 4] = 1  # status, not HP; preserve structure
    bank_index = 1
    sram[codec.SRAM_LAYOUT["individual_checksums"][bank_index] + 5] = (
        codec.sav_checksum(sram[box:box + codec.BOX_SIZE]))
    bank = codec.SRAM_LAYOUT["box_banks"][bank_index]
    end = codec.SRAM_LAYOUT["all_boxes_checksums"][bank_index]
    sram[end] = codec.sav_checksum(sram[bank:end])
    path.write_bytes(sram)
    with pytest.raises(RuntimeError, match="HP0000/status00"):
        run.assert_linked_faint_saved(results, active=False)
    print("synthetic bench faint: PASS; boxed status corruption: FAIL")


def test_synthetic_active_faint_oracle_requires_loop_write_before_engine_site(tmp_path, capsys):
    run, _paths, a_text, b_text = _linked_faint_fixture(tmp_path, "linked_faint_active_new")
    proper = (b_text + "LOOP_HEAD_WRITE key=" + run._link_keys["b"] + "\n"
              + "BATTLE_FAINT_SITE " + run._link_keys["b"] + "\n"
              + f'TX {{"event":"faint","key":"{run._link_keys["b"]}"}}\n'
              + "TILEMAP_FAINTED offset=123\nBATTLE_RESULT b 2\n")
    run.assert_linked_faint_saved({"a": a_text, "b": proper}, active=True)
    assert "Box 12" in capsys.readouterr().out
    run.assert_linked_faint_saved({"a": a_text, "b": proper.replace(
        "TILEMAP_FAINTED offset=123\n", "TILEMAP_FAINTED unavailable: native faint text advanced before probe\n")},
        active=True)
    reversed_order = (b_text + "BATTLE_FAINT_SITE " + run._link_keys["b"] + "\n"
                      + "LOOP_HEAD_WRITE key=" + run._link_keys["b"] + "\n"
                      + f'TX {{"event":"faint","key":"{run._link_keys["b"]}"}}\n'
                      + "TILEMAP_FAINTED offset=123\nBATTLE_RESULT b 2\n")
    with pytest.raises(RuntimeError, match="not followed by engine battle_faint"):
        run.assert_linked_faint_saved({"a": a_text, "b": reversed_order}, active=True)
    print("synthetic active faint: PASS; reversed loop/engine order: FAIL")


@pytest.mark.parametrize(("mode", "faint_after", "expected", "encounters", "start_active"), [
    ("sacrifice", 2, "linked-fainted", 1, False),
    ("sacrifice", 999, "linked-survived-3-battles", 3, False),
    ("switch-hold", 999, "linked-active-menu", 1, False),
    ("switch-hold", 999, "linked-active-menu", 1, True),
])
def test_hunt_switch_and_three_encounter_sacrifice_bound(mode, faint_after, expected, encounters, start_active):
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval(f'dofile("{(REPO / "lua/tests/gen1_rb_hunt_inputs.lua").as_posix()}")')
    moves = {"count": 0}
    fainted = lua.eval("function(cb) return function() return cb() end end")(
        lambda: moves["count"] >= faint_after)

    def commit(_slot, _budget):
        moves["count"] += 1
        return lua.table(why="player_move" if faint_after < 999 else "battle_over")

    switches = []

    def switch_to(slot, _budget):
        switches.append(slot)
        return lua.table(ok=True, why="switched")

    driver = lua.table(wait_menu=lambda _budget: lua.table(ok=True, frames=1),
                       switch_to=switch_to,
                       choose=lambda _name: lua.table(ok=True), commit_move=commit)
    route = module.new(lua.table(player="a"), lua.table(
        driver=driver, step=lambda _buttons: None, rd=lambda _addr: 0,
        symbols=lua.table(wNumBagItems=1, wBagItems=2),
        mode=mode, move_slot=1, switch_slot=1, fainted=fainted, start_active=start_active))
    battle = lua.table(map=12, x=10, y=35, battle=1, battle_type=0, party_hp=10,
                       party_count=2, font_loaded=False, joy_ignore=0)
    overworld = lua.table(map=12, x=10, y=35, battle=0, battle_type=0, party_hp=10,
                          party_count=2, font_loaded=False, joy_ignore=0)
    phase = None
    for index in range(encounters):
        _buttons, phase = route.step(None, None, battle, 2 * index + 1)
        if phase == expected:
            break
        _buttons, phase = route.step(None, None, overworld, 2 * index + 2)
        if phase == expected:
            break
    assert phase == expected
    assert route.encounters == encounters
    assert switches == ([] if start_active else [1] * encounters)
