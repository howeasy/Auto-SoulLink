"""Executed artifact selection for all Gen 2 duo cells, without an emulator."""

import hashlib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import e2e_duo as duo


def test_every_gen2_scenario_can_explicitly_select_overlay():
    args = SimpleNamespace(gen2_artifact="overlay")
    assert duo.gen2_selected_artifact(args, "gen2_pc_ops") == "overlay"
    assert duo.gen2_selected_artifact(args, "link") == "overlay"


def test_native_trade_never_falls_back_to_clean():
    with pytest.raises(ValueError, match="trade requires overlay"):
        duo.gen2_selected_artifact(SimpleNamespace(gen2_artifact="clean"), "gen2_trade_new")


def test_legacy_default_is_clean_for_gameplay_and_overlay_for_native_trade(monkeypatch):
    monkeypatch.delenv("SLINK_GEN2_ARTIFACT", raising=False)
    assert duo.gen2_selected_artifact(SimpleNamespace(), "link") == "clean"
    assert duo.gen2_selected_artifact(SimpleNamespace(), "gen2_trade_new") == "overlay"


@pytest.mark.parametrize("game,title", [("gen2_new", "crystal"), ("gen2_gold_silver", "gold")])
def test_overlay_preparation_keeps_refused_b_cartridge_and_launch_identity(tmp_path, monkeypatch, game, title):
    monkeypatch.syspath_prepend(str(Path(duo.__file__).resolve().parent))
    import run_gb_gate as gate

    from tests.live import test_gen2_frame_align as align, test_gen2_new_gates as inspect
    from tools import gen2_fixtures

    emu = tmp_path / "emu/EmuHawk.exe"
    emu.parent.mkdir()
    emu.touch()
    db = emu.parent / "gamedb/gamedb_gbc.txt"
    db.parent.mkdir()
    wrong = tmp_path / "pokecrystal11.gbc"
    wrong.write_bytes(b"MODEL refused Crystal 1.1")
    wrong_sha = hashlib.sha1(wrong.read_bytes()).hexdigest()
    db.write_text(wrong_sha.upper() + "\tG\tCrystal 1.1 MODEL\tGBC\n")
    build = tmp_path / "patch/build"
    monkeypatch.setattr(duo, "EMUHAWK", str(emu))
    monkeypatch.setattr(duo, "BUILD", str(build))
    rows = {}
    for side, own in (("a", title), ("b", "crystal")):
        fixture = tmp_path / f"{side}.SaveRAM"
        fixture.write_bytes(side.encode())
        rows[side] = {"title": own, "name": f"{own}_battle", "fixture": fixture,
                      "qualification_attempt_id": "MODEL", "rom": wrong if side == "b" else build / "a.gbc",
                      "rom_sha1": wrong_sha if side == "b" else "a" * 40}
    rows["b"]["expect_admission"] = "refused"
    def plan(key, directory, fixture, speed):
        own = key.removesuffix("_overlay")
        stage = b"MODEL overlay " + own.encode() if key.endswith("_overlay") else None
        sha = hashlib.sha1(stage).hexdigest() if stage else "c" * 40
        return {"title": own, "artifact": "poke" + own, "rom": build / f"{own}.gbc", "stage": stage,
                "launch_sha1": sha, "rom_sha1": "c" * 40, "base_sha1": "c" * 40,
                "kind": "overlay" if stage else "clean", "overlay": stage is not None,
                "env": {"SLINK_GEN2_ROM_SHA1": "c" * 40, "SLINK_GEN2_BASE_SHA1": "c" * 40,
                        "SLINK_GEN2_EXEC_SHA1": sha, "SLINK_GEN2_ARTIFACT_KIND": "overlay" if stage else "clean",
                        "SLINK_GEN2_OVERLAY_SHA1": sha, "SLINK_GEN2_BINDING_SHA256": "b" * 64}}
    monkeypatch.setattr(duo, "gen2_preflight", lambda **kw: rows)
    monkeypatch.setitem(gate.GENS["gen2"], "plan", plan)
    monkeypatch.setattr(gen2_fixtures, "exec_context", lambda *a: SimpleNamespace(title=title))
    monkeypatch.setattr(gen2_fixtures, "spec_route_facts", lambda *a, **kw: {})
    monkeypatch.setattr(inspect, "inspect_env", lambda *a, **kw: {"SLINK_GEN2_FIXTURE_CASE": "{}"})
    monkeypatch.setattr(align, "u1_facts", lambda *a: {})
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.args = SimpleNamespace(gen2_artifact="overlay")
    run.game, run.scenario, run.attempt = game, "gen2_admit_wrong_rom", 1
    run.gcfg = duo.GAMES[game]
    run._timed = lambda *_a: nullcontext()
    run._saveram_dir = lambda side: str(tmp_path / side)
    run.gen2_speed = lambda: 300
    run._check_bizhawk_paths = lambda: None
    run._prepare_gen2_lane()
    refused = run._gen2_plans["b"]
    assert rows["b"]["rom"] == refused["rom"] == wrong
    assert rows["b"]["rom_sha1"] == refused["rom_sha1"] == refused["launch_sha1"] == wrong_sha
    assert refused["stage"] is None and refused["overlay"] is False and refused["kind"] == "clean"
    env = refused["env"]
    assert all(env[key] == wrong_sha for key in ("SLINK_GEN2_ROM_SHA1", "SLINK_GEN2_BASE_SHA1", "SLINK_GEN2_EXEC_SHA1"))
    assert env["SLINK_GEN2_ARTIFACT_KIND"] == "clean"
    assert "SLINK_GEN2_OVERLAY_SHA1" not in env and "SLINK_GEN2_BINDING_SHA256" not in env
    assert refused["saveram_name"] == env["SLINK_GEN2_SAVERAM_NAME"] == "Crystal 1.1 MODEL.SaveRAM"
    admitted = run._gen2_plans["a"]
    assert admitted["kind"] == "overlay" and Path(admitted["rom"]).read_bytes() == admitted["stage"]
