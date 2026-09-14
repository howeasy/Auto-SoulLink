"""F-4 runner orchestration with fake UPR outputs and server receipts; no jar or emulator."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402
from run_gb_gate import GENS  # noqa: E402

from server import upr_pipeline  # noqa: E402
from server.adapters import gen1_rom_scan as scan  # noqa: E402
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
