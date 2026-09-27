"""X2: lua/gen3/reads.lua's battle geometry comes from the profile (the expansion reference build's
BattlePokemon is 140 bytes with hp at +42, not vanilla's 0x58/+0x28); vanilla packs unchanged."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = "emerald_expansion_28877d73"


def _profile(pack, title):
    return json.loads((ROOT / "data/games" / pack / "profile.json").read_text(encoding="utf-8"))["titles"][title]


def _reads(profile, reads_log):
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/reads.lua").read_text(encoding="utf-8"))
    reads_log.append(lua)                  # the runtime, for the caller's Lua tables

    def read_bytes(addr, n):
        reads_log.append(addr)
        return lua.table(*([6] * n))

    io = lua.table(read_u8=lambda a: 2, read_u16=lambda a: 0, read_u32=lambda a: reads_log.append(a) or 0,
                   read_bytes=read_bytes)
    return module.new(lua.table_from(profile, recursive=True), io)


@pytest.mark.parametrize("pack,title,size", [("gen3_exp/28877d73", EXP, 140),
                                             ("gen3_emerald", "emerald", 0x58),
                                             ("gen3_frlg", "firered", 0x58)])
def test_the_battler_stride_is_the_titles_own(pack, title, size):
    profile, log = _profile(pack, title), []
    r = _reads(profile, log)
    lua = log.pop(0)
    base = profile["ram"]["BATTLE_MONS_ADDR"]
    r.read_stat_stages(1)
    assert log[-1] == base + size + profile["derived"]["BATTLE_MON_STAT_STAGES_OFF"]
    r.battler_holds(1, lua.table_from({"personality": 0, "ot_id": 0}))
    assert base + size + profile["derived"]["BATTLE_MON_PERSONALITY_OFF"] in log
    assert size == r.BATTLE_MON_SIZE
    assert (42 if title == EXP else 0x28) == r.BATTLE_MON_HP_OFF


def test_the_expansion_profile_carries_its_battle_geometry():
    facts = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text())["structs"]["BattlePokemon"]
    d = _profile("gen3_exp/28877d73", EXP)["derived"]
    assert (d["BATTLE_MON_SIZE"], d["BATTLE_MON_HP_OFF"]) == (facts["size"], facts["fields"]["hp"]["offset"])
