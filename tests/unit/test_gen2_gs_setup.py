"""MODEL: SYNTH writes preserve identity; a native hook cannot seed the wrong battle."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.adapters import gen2_codec
from tools.gen2_synth_fixtures import _Save
from tools.gen2_trade_facts import trade_facts

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "lua/tests/duo/gen2_gs_setup.lua"


def rig(title="gold"):
    lua = LuaRuntime(unpack_returned_tuples=True)
    layout = gen2_codec.for_foundation(title, root=ROOT)
    base = _Save((ROOT / f"tests/fixtures/gen2/{title}_battle_errand.SaveRAM").read_bytes(), layout)
    raw = base.read("wPartyMon1", layout.party_size)
    marker = base.read("wPartySpecies", 1)[0]
    mon = gen2_codec.decode_party_mon(raw, layout, species_marker=marker)
    native = trade_facts(title, root=ROOT)
    index = json.loads((ROOT / f"data/games/gen2_{title}/species_index.json").read_text())["species"]
    species = {key: {"base_stats": row["base_stats"], "exp": gen2_codec.exp_for_level(20, row["growth_rate"])}
               for key, row in index.items() if row["classification"] == "ordinary"}
    facts = {"schema": "gen2-gs-harden-v1", "title": title, "overlay_sha1": native["overlay_sha1"],
             "level": 20, "species": species, "site": native["code"]["StartBattle"], "ram": native["ram"]}
    g = lua.globals()
    g.FACTS = lua.table_from(facts, recursive=True)
    g.CONSTANTS = lua.table_from(layout.constants)
    g.ORIGINAL = lua.table_from(list(raw))
    g.SPECIES = marker
    lua.execute('''
mem, logs, handles, unregisters = {}, {}, {}, 0
local function offset(bank, addr) return addr < 0xD000 and addr - 0xC000 or bank * 0x1000 + addr - 0xD000 end
local function poke(name, value, delta)
    local r = FACTS.ram[name]
    mem[offset(r.bank, r.addr + (delta or 0))] = value
end
POKE = poke
poke("wPartyCount", 1); poke("wPartySpecies", SPECIES)
for i,v in ipairs(ORIGINAL) do poke("wPartyMon1", v, i-1) end
poke("wBattleMode", 0); poke("wOtherTrainerClass", 0); poke("wBattleType", 0)
poke("wMapGroup", 26); poke("wMapNumber", 1); poke("wTempWildMonSpecies", 161)
api = {
    read_range=function(at,n) local r={} for i=1,n do r[i]=mem[at+i-1] or 0 end return r end,
    write_u8=function(at,v) mem[at]=v end,
    read_u8=function(at,domain) if domain=="ROM" then return tonumber(FACTS.site.hex,16) end return bank or FACTS.site.bank end,
    on_bus_exec=function(fn) handles[1]=fn; return 1 end,
    unregister=function(id) handles[id]=nil; unregisters=unregisters+1 end,
}
ctx={api=api, env={title=FACTS.title, exec_sha1=FACTS.overlay_sha1}, profile={constants=CONSTANTS,hram={hROMBank=0xFF9D}},
     facts={maps={Route29={map_group=26,map_number=1}}}}
SG={wram_offset=offset}
h={frame=function() return 100 end, jlog=function(tag,row) logs[#logs+1]={tag=tag,row=row} end,
   slot_of=function() return 0 end,
   encounter=function()
       handles[1]()
       local r=FACTS.ram.wTempWildMonSpecies
       return true, mem[offset(r.bank,r.addr)]
   end}
''')
    module = lua.execute(HELPER.read_text())
    helper = module.new(g.h, g.ctx, g.SG, g.FACTS)
    return lua, helper, layout, mon, species


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_conditioning_has_coherent_hp_stats_exp_and_preserves_every_other_record_byte(title):
    lua, helper, layout, original, species = rig(title)
    assert helper.condition_starter() is True
    row = lua.globals().logs[1].row
    after = bytes.fromhex(row.bytes_after)
    decoded = gen2_codec.decode_party_mon(after, layout, species_marker=original["species_marker"])
    expected_stats = gen2_codec.calc_stats(species[str(original["species_id"])]["base_stats"],
                                         original["dvs"], original["stat_exp"], 20)
    assert decoded["level"] == 20 and decoded["exp"] == species[str(original["species_id"])]["exp"]
    assert decoded["hp"] == decoded["max_hp"] == expected_stats["hp"]
    assert decoded["stats"] == {key: value for key, value in expected_stats.items() if key != "hp"}
    changed = set(range(layout.constants["MON_EXP"], layout.constants["MON_EXP"] + 3))
    changed.add(layout.constants["MON_LEVEL"])
    changed.update(range(layout.constants["MON_HP"], layout.party_size))
    before = bytes.fromhex(original["raw_hex"])
    assert all(after[i] == before[i] for i in range(layout.party_size) if i not in changed)
    assert helper.condition_starter() is True and len(lua.globals().logs) == 1


@pytest.mark.parametrize("field,value", [("wBattleMode", 1), ("wPartySpecies", 253)])
def test_conditioning_refuses_an_active_battle_or_egg_without_writes(field, value):
    lua, helper, _, _, _ = rig()
    lua.globals().POKE(field, value)
    ok, _why = helper.condition_starter()
    assert ok is False and len(lua.globals().logs) == 0


@pytest.mark.parametrize("field,value", [("wBattleMode", 2), ("wOtherTrainerClass", 1), ("wMapGroup", 24)])
def test_species_hook_cannot_plant_a_trainer_or_wrong_map_and_always_unregisters(field, value):
    lua, helper, _, _, _ = rig()
    lua.globals().POKE(field, value)
    ok, why = helper.encounter(16)
    assert ok is False and why == "StartBattle species setup never fired"
    assert len(lua.globals().logs) == 0 and lua.globals().unregisters == 1


def test_species_hook_selects_before_native_generation_and_unregisters():
    lua, helper, _, _, _ = rig()
    assert helper.encounter(16) == (True, 16)
    row = lua.globals().logs[1].row
    assert row.purpose == "gs_species_encounter" and row.bytes_before == "a1" and row.bytes_after == "10"
    assert lua.globals().unregisters == 1
