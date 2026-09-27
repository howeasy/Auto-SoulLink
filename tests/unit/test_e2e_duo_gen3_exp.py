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
CORE = ("faint_cmd_gen3", "link_gen3", "whiteout_gen3", "boxsync_gen3", "linked_faint_active_gen3")


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
