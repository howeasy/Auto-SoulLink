"""X3: the gen3_exp duo row (the expansion reference build, E<->E) in tools/e2e_duo.py and the
duo driver's TEST-ONLY admission seam (lua/tests/duo/duo_gen3_main.lua test_admission_codec)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import e2e_duo as duo  # noqa: E402

EXP = "emerald_expansion_28877d73"
DRIVER = REPO / "lua" / "tests" / "duo" / "duo_gen3_main.lua"
CORE = ("faint_cmd_gen3", "link_gen3", "whiteout_gen3", "boxsync_gen3")


def test_the_active_faint_row_is_not_claimed_without_a_perish_plan():
    """Hold fallback until XG3: the pack carries none of the Perish+hand-off inputs the client's
    active_faint_capable needs, so an active battler's force_faint is held, never committed."""
    derived = json.loads((REPO / "data/games/gen3_exp/28877d73/profile.json").read_text())["titles"][EXP]
    assert not {"STATUS3_ADDR", "DISABLE_STRUCTS_ADDR"} & set(derived["ram"])
    assert not {"STATUS3_PERISH_SONG", "DISABLE_STRUCT_SIZE"} & set(derived["derived"])
    assert "gen3_exp" not in duo.SCENARIOS["linked_faint_active_gen3"]["games"]
    cp = json.loads((REPO / "data/games/gen3_exp/28877d73/write_checkpoint.json").read_text())[EXP]
    assert "handoff" not in cp["battle"] and cp["battle"]["commit_hold"].startswith("OPEN")


def test_the_row_runs_the_core_loop_rows_on_its_own_fixtures():
    row = duo.GAMES["gen3_exp"]
    assert row["game"] == "gen3_exp" and "gen3_exp" in duo.OPT_IN_GAMES and duo.rng_retry_family("gen3_exp")
    assert set(CORE) <= set(duo.scenarios_for("gen3_exp"))
    assert duo.gen3_profile_path(EXP).endswith(os.path.join("gen3_exp/28877d73", "profile.json"))
    assert duo.gen3_codec_title(EXP) == EXP and duo.gen3_emerald_engine(EXP) and duo.gen3_emerald_engine("emerald")
    assert not duo.gen3_emerald_engine("firered")
    for name in CORE:
        run = duo.DuoRun.__new__(duo.DuoRun)
        run.gcfg, run.cfg, run.game = dict(row), dict(duo.SCENARIOS[name]), "gen3_exp"
        assert run._hunt_area == {"pc": "route_103", "catch": "route_102"}[run._target_for("a")], name
        for inst in ("a", "b"):
            assert run._gen3_title(inst) == EXP
            assert os.path.isfile(run._gen3_fixture_path(inst)), run._gen3_fixture_path(inst)


def test_saved_state_decodes_through_the_builds_masked_layout():
    image = (REPO / "tests/fixtures/gen3/exp_pc.sav").read_bytes()
    party, boxes = duo.gen3_decode(image, title=EXP)
    assert [m["species"] for m in party] == [258, 261] and sorted(m["species"] for m in boxes.values()) == [263, 265]
    assert all(m["pokeball"] == 1 for m in party)
    assert duo.gen3_ball_count(image, EXP) == 5
    limits = duo.gen3_limits(EXP)
    assert limits["species"](1572) and not limits["species"](1573) and not limits["species"](0)


def test_the_rom_is_the_staged_reference_artifact(tmp_path, monkeypatch):
    rom = tmp_path / "pokeemerald.gba"
    rom.write_bytes(b"not really")
    monkeypatch.setenv("SLINK_EXPANSION_ARTIFACTS", str(tmp_path))
    staged = []
    monkeypatch.setattr(duo.__dict__.get("gen3_fixtures") or __import__("gen3_fixtures"), "stage_rom",
                        lambda path: staged.append(path) or "patch/build/gen3_pokeemerald.gba")
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg, run.game = dict(duo.GAMES["gen3_exp"]), dict(duo.SCENARIOS["faint_cmd_gen3"]), "gen3_exp"
    assert run._gen3_rom("a") == "patch/build/gen3_pokeemerald.gba" and staged == [str(rom)]
    rom.unlink()
    with pytest.raises(FileNotFoundError, match="build_expansion"):
        run._gen3_rom("a")


_ADMISSION_FN = re.compile(r"local function test_admission_codec\(.*?\nend\n", re.S)


def test_admission_seam_fires_only_on_the_gen3_exp_row():
    from lupa import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    body = _ADMISSION_FN.search(DRIVER.read_text(encoding="utf-8"))
    assert body, "duo_gen3_main.lua must define test_admission_codec"
    fn = lua.execute(body.group(0) + "\nreturn test_admission_codec")
    codec = lua.execute(f"return dofile([[{REPO / 'lua' / 'json_codec.lua'}]])")
    same, logged = lua.eval("rawequal"), []
    for game in ("gen3_frlg", "gen3_rr", "gen3_emerald", "gen1_new", None):
        assert same(fn(game, EXP, codec, logged.append), codec)
    wrapped = fn("gen3_exp", EXP, codec, logged.append)
    doc = wrapped.decode(json.dumps({"titles": {EXP: {"admitted": False}, "emerald": {"admitted": False}}}))
    assert doc.titles[EXP].admitted is True and doc.titles.emerald.admitted is False
    assert logged == [f"TEST-ONLY admission of gen3_exp/{EXP} (pre-XG; production refuses)"]


def test_production_still_refuses_the_expansion_build():
    profile = json.loads((REPO / "data/games/gen3_exp/28877d73/profile.json").read_text(encoding="utf-8"))
    assert profile["titles"][EXP]["admitted"] is False
    entry = (REPO / "lua/gen3/entry.lua").read_text(encoding="utf-8")
    assert re.search(r"(?m)^Entry\.ROUTED = \{ gen3_frlg = true, gen3_rr = true, gen3_emerald = true \}", entry)
    assert "test_admission_codec" not in entry


_SAVE_CONTRACT_FN = re.compile(r"local function save_contract_holds\(.*?\nend\n", re.S)


@pytest.mark.parametrize("point,ok", [
    ({"R0": 1, "R5": 0, "R13": 1}, True),            # the vanilla packs' point (R5 = saveType)
    ({"R0": 1, "R4": 0, "R15": 1, "CPSR": 1}, True),  # the expansion site's point (R4 = saveType)
    ({"R0": 1, "R4": 3, "R15": 1}, False),           # not SAVE_NORMAL
    ({"R0": 0, "R5": 0}, False),                     # the save failed
    ({"R0": 1}, False),                              # no save-type register captured
])
def test_the_save_witness_reads_the_sites_own_save_type_register(point, ok):
    from lupa import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    body = _SAVE_CONTRACT_FN.search(DRIVER.read_text(encoding="utf-8"))
    assert body, "duo_gen3_main.lua must define save_contract_holds"
    fn = lua.execute(body.group(0) + "\nreturn save_contract_holds")
    got = fn(lua.table_from(point))
    assert (got[0] if isinstance(got, tuple) else got) is ok
    sites = json.loads((REPO / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
    assert "R4" in sites["titles"][EXP]["artifacts"]["clean"]["sites"]["save"]["point"]


def test_battle_geometry_is_the_builds_compiler_facts_and_vanilla_is_unchanged():
    """Live whiteout_gen3 on 28877d73 read no status move: the driver's vanilla gBattleMons
    offsets (pp +0x24, hp +0x28, stride 0x58) and move power (byte 1) are wrong on the expansion
    build, whose BattlePokemon is 140 bytes and whose MoveInfo.power is a 9-bit field."""
    facts = json.loads((REPO / "data/games/gen3_exp/28877d73/facts.json").read_text())["structs"]
    bp, power = facts["BattlePokemon"], facts["MoveInfo"]["bitfields"]["power"]
    assert (bp["size"], bp["fields"]["moves"]["offset"], bp["fields"]["pp"]["offset"],
            bp["fields"]["hp"]["offset"]) == (140, 0x0C, 37, 42)
    assert (power["offset"], power["width"], power["shift"], power["bits"]) == (10, 2, 7, 9)
    src = DRIVER.read_text(encoding="utf-8")
    assert ("local BM = { size = 0x58, moves = 0x0C, pp = 0x24, hp = 0x28,\n"
            "             power = { off = 1, width = 1, shift = 0, mask = 0xFF }, effect_off = 0 }") in src
    assert "if title == TITLES.EXP_TITLE then" in src and "st.BattlePokemon, st.MoveInfo.bitfields.power" in src
    for literal in ("S.gBattleMons + 0x28", "base + 0x24 + slot", "+ 0x58 + 0x28"):
        assert literal not in src, literal


def test_the_whiteout_landing_is_the_oldale_center_respawn_not_the_outdoor_tile():
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.gcfg, run.cfg, run.game = dict(duo.GAMES["gen3_exp"]), dict(duo.SCENARIOS["whiteout_gen3"]), "gen3_exp"
    assert run._gen3_fixture_heal_tile("a") == r"map=2\.2 at=\(7,4\)"
    emerald = duo.DuoRun.__new__(duo.DuoRun)
    emerald.gcfg, emerald.cfg, emerald.game = (dict(duo.GAMES["gen3_emerald"]),
                                               dict(duo.SCENARIOS["whiteout_gen3"]), "gen3_emerald")
    assert emerald._gen3_fixture_heal_tile("a") == r"map=0\.10 at=\(6,17\)"
