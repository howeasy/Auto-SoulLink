"""W-1..W-4, W-7 (MODEL): lua/gen1/writes.lua puts bytes exactly where pret says, and nowhere
without an armed write window. Fake bytearray WRAM under lupa; the Python codec reads back
what Lua wrote.
"""
from __future__ import annotations

import json
import pathlib
import random

import lupa
import pytest

from server.adapters import gen1_codec as codec

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILE = json.loads((REPO / "data" / "games" / "gen1_rby" / "profile.json").read_text(encoding="utf-8"))["titles"]
WRITES_LUA = (REPO / "lua" / "gen1" / "writes.lua").as_posix()


class Fake:
    def __init__(self, title="red"):
        self.title = title
        self.ram = PROFILE[title]["ram"]
        self.d = PROFILE[title]["derived"]
        self.mem = bytearray(0x10000)
        self.writes: list[tuple[int, int]] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        io = self.lua.table(
            read_u8=lambda a, dom: self.mem[int(a)],
            write_u8=self._write_u8,
        )
        self.W = self.lua.eval(f'dofile("{WRITES_LUA}")')
        prof = self.lua.table_from(PROFILE[title], recursive=True)
        self.w = self.W.new(prof, io)

    def _write_u8(self, addr, value, domain):
        assert str(domain) == "System Bus"
        self.mem[int(addr)] = int(value)
        self.writes.append((int(addr), int(value)))

    # Lua method calls from Python need self passed explicitly.
    def call(self, name, *args):
        return getattr(self.w, name)(self.w, *args)

    def party_slot(self, slot: int) -> bytes:
        base = self.ram["wPartyMons"] + slot * self.d["party_struct_size"]
        return bytes(self.mem[base:base + self.d["party_struct_size"]])

    def seed_party(self, mons):
        self.mem[self.ram["wPartyCount"]] = len(mons)
        for i, m in enumerate(mons):
            self.mem[self.ram["wPartySpecies"] + i] = m["species"]
            base = self.ram["wPartyMons"] + i * self.d["party_struct_size"]
            self.mem[base:base + 44] = codec.encode_party_mon(m)
        self.mem[self.ram["wPartySpecies"] + len(mons)] = 0xFF


def _mon(rng, species=1):
    m = codec.decode_party_mon(bytes(rng.randrange(256) for _ in range(44)))
    m["species"] = species
    m["hp"] = rng.randrange(1, 200)
    m["status"] = 0x08  # poisoned, so we can see it cleared
    return m


def test_nothing_is_written_without_an_armed_window():
    f = Fake()
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        f.call("faint_party_slot", 0)
    assert f.writes == []
    f.call("arm", "overworld")
    f.call("faint_party_slot", 0)
    assert f.writes
    f.call("disarm")
    with pytest.raises(lupa.LuaError, match="no armed write window"):
        f.call("faint_party_slot", 0)


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
def test_bench_faint_zeroes_hp_and_status_of_that_slot_only(title):
    rng = random.Random(7)
    f = Fake(title)
    mons = [_mon(rng, 1 + i) for i in range(3)]
    f.seed_party(mons)
    before = [f.party_slot(i) for i in range(3)]
    f.call("arm", "overworld")
    f.call("faint_party_slot", 1)
    after = codec.decode_party_mon(f.party_slot(1))
    assert after["hp"] == 0 and after["status"] == 0
    # only HP (2 bytes) and status (1 byte) of slot 1 changed
    changed = {a for a, _ in f.writes}
    base = f.ram["wPartyMons"] + f.d["party_struct_size"]
    assert changed == {base + 1, base + 2, base + 4}
    assert f.party_slot(0) == before[0] and f.party_slot(2) == before[2]


def test_active_battler_faint_needs_the_loop_head_and_hits_both_structs():
    rng = random.Random(9)
    f = Fake()
    f.seed_party([_mon(rng, 4)])
    f.mem[f.ram["wBattleMonHP"]] = 0x00
    f.mem[f.ram["wBattleMonHP"] + 1] = 0x2A
    f.call("arm", "overworld")
    with pytest.raises(lupa.LuaError, match="only at the battle loop head"):
        f.call("faint_active_battler", 0)
    f.call("arm", "battle_loop_head")
    f.call("faint_active_battler", 0)
    assert f.mem[f.ram["wBattleMonHP"]] == 0 and f.mem[f.ram["wBattleMonHP"] + 1] == 0
    assert f.mem[f.ram["wPlayerSelectedMove"]] == 0xFF
    assert codec.decode_party_mon(f.party_slot(0))["hp"] == 0


def test_active_faint_guard_rules():
    f = Fake()
    guard = f.W.active_faint_guard
    L = f.lua.table
    mon = L(species=4)
    assert guard(L(in_battle=1, type=0, link_state=0, player_mon_number=0, battle_species=4, transformed=False), 0, mon) is True
    assert guard(L(in_battle=0, type=0, link_state=0, player_mon_number=0, battle_species=4), 0, mon)[1] == "not in a battle"
    assert "special battle" in guard(L(in_battle=1, type=2, link_state=0, player_mon_number=0, battle_species=4), 0, mon)[1]
    assert "link" in guard(L(in_battle=1, type=0, link_state=4, player_mon_number=0, battle_species=4), 0, mon)[1]
    assert "not the active" in guard(L(in_battle=1, type=0, link_state=0, player_mon_number=2, battle_species=4), 0, mon)[1]
    assert "species differs" in guard(L(in_battle=1, type=0, link_state=0, player_mon_number=0, battle_species=9), 0, mon)[1]
    # Transform: the battle struct shows the foe's species; the party slot is still ours
    assert guard(L(in_battle=1, type=0, link_state=0, player_mon_number=0, battle_species=9, transformed=True), 0, mon)[0] is True


def test_explode_fills_all_four_slots_in_both_structs():
    rng = random.Random(3)
    f = Fake("yellow")
    f.seed_party([_mon(rng, 4)])
    f.call("arm", "battle_loop_head")
    f.call("explode_active_battler", 0)
    assert list(f.mem[f.ram["wBattleMonMoves"]:f.ram["wBattleMonMoves"] + 4]) == [0x99] * 4
    assert list(f.mem[f.ram["wBattleMonPP"]:f.ram["wBattleMonPP"] + 4]) == [1] * 4
    slot = codec.decode_party_mon(f.party_slot(0))
    assert slot["moves"] == [0x99] * 4 and slot["pp"] == [1] * 4


def test_enemy_party_is_validated_completely_before_any_byte_lands():
    rng = random.Random(5)
    f = Fake()
    good = [_mon(rng, 20), _mon(rng, 21)]
    bad = _mon(rng, 22)
    L = f.lua.table

    def entry(m, blob=None):
        b = blob if blob is not None else list(codec.encode_party_mon(m))
        return L(species=m["species"], blob=L(*b), ot=L(*([0x80] * 10 + [0x50])), nick=L(*([0x81] * 10 + [0x50])))

    f.call("arm", "overworld")
    with pytest.raises(lupa.LuaError, match="enemy mon 3: blob must be 44 bytes"):
        f.call("write_enemy_party", L(entry(good[0]), entry(good[1]), entry(bad, blob=[1, 2, 3])))
    assert f.writes == [], "a bad third blob must not leave the first two half-written"
    f.call("write_enemy_party", L(entry(good[0]), entry(good[1])))
    assert f.mem[f.ram["wEnemyPartyCount"]] == 2
    assert list(f.mem[f.ram["wEnemyPartySpecies"]:f.ram["wEnemyPartySpecies"] + 3]) == [20, 21, 0xFF]
    got = codec.decode_party_mon(bytes(f.mem[f.ram["wEnemyMons"] + 44:f.ram["wEnemyMons"] + 88]))
    assert got["species"] == 21 and got["dvs"] == good[1]["dvs"]
    ot = f.mem[f.ram["wEnemyMonOT"] + 11:f.ram["wEnemyMonOT"] + 22]
    assert bytes(ot) == bytes([0x80] * 10 + [0x50])
