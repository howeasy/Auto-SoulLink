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
PANEL_LUA = (REPO / "lua" / "gen1" / "panel.lua").as_posix()
ENTRY_LUA = (REPO / "lua" / "gen1" / "entry.lua").as_posix()


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
        self.prof = self.lua.table_from(PROFILE[title], recursive=True)
        self.w = self.W.new(self.prof, io)

    def panel_allow(self):
        """The REAL predicate lua/gen1/panel.lua arms its window with, not a copy of it."""
        P = self.lua.eval(f'dofile("{PANEL_LUA}")')
        pio = self.lua.table(read_u8=lambda a: self.mem[int(a)], framecount=lambda: 0)
        return P.new(self.prof, pio, self.w, lambda s: s).allow

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
    assert guard(L(in_battle=1, type=0, link_state=0, player_mon_number=0, battle_species=9, transformed=True), 0, mon) is True


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


# ── the panel write window (A11) ───────────────────────────────────────────────────────────
# The 5th window is the first one that is NARROWER than "anywhere in WRAM": the panel paints
# while the patch holds a white screen, so a row that runs one byte past wTileMap would land
# in wTopMenuItemY and steer the menu the player is standing in. write_bytes therefore checks
# the FULL interval, not just the first byte.
TILEMAP = PROFILE["red"]["ram"]["wTileMap"]   # $C3A0
TILES = 360
STATE, PAGES = 0xDEEB, 0xDEED                 # slink.asm mailbox +9 / +11


def test_the_panel_window_refuses_a_write_that_straddles_the_end_of_its_allow_set():
    f = Fake()
    allow = f.panel_allow()
    f.call("arm", "panel", allow)
    with pytest.raises(lupa.LuaError, match="outside the panel window"):
        f.call("write_bytes", TILEMAP + TILES - 1, f.lua.table(0x80, 0x81))
    assert f.writes == [], "a straddling write must not land its first byte"
    f.call("write_bytes", TILEMAP + TILES - 2, f.lua.table(0x80, 0x81))
    assert list(f.mem[TILEMAP + TILES - 2:TILEMAP + TILES]) == [0x80, 0x81]
    # the two mailbox bytes are single-byte holes, not a range
    f.call("write_bytes", PAGES, f.lua.table(2))
    assert f.mem[PAGES] == 2
    with pytest.raises(lupa.LuaError, match="outside the panel window"):
        f.call("write_bytes", STATE, f.lua.table(2, 0))


def test_disarm_clears_the_predicate_as_well_as_the_reason():
    f = Fake()
    f.call("arm", "panel", f.panel_allow())
    f.call("disarm")
    f.call("arm", "overworld")
    f.call("write_bytes", f.ram["wPartyMons"], f.lua.table(7))
    assert f.mem[f.ram["wPartyMons"]] == 7, "a window armed with no predicate is unrestricted"


def _entry_parts(cart_writes):
    """entry.lua's REAL box_io, built by Entry.build over a stub BizHawk."""
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    io = L.table(read_u8=lambda a, d=None: 0, read_range=lambda a, n, d=None: L.table(*[0] * int(n)),
                 write_u8=lambda a, v, d=None: cart_writes.append((int(a), int(v), str(d))),
                 on_bus_exec=lambda *a: 1, unregister=lambda i: None, framecount=lambda: 0,
                 register=lambda n: 0, domains=lambda: L.table("System Bus", "ROM", "CartRAM"))
    net = L.table(init=lambda h, p: None, connected=lambda: False, pump=lambda: None,
                  send=lambda line: None, receive=lambda: None)
    hud = L.table(show=lambda *a: None, prompt=lambda *a: None, set_game_over=lambda: None,
                  set_rebuilding=lambda t: None, clear_rebuilding=lambda: None)
    E = L.eval(f'dofile("{ENTRY_LUA}")')
    _client, parts = E.build(L.table(root=REPO.as_posix(), io=io, net=net, hud=hud, title="red",
                                     player="a", rom_sha1="x", log=lambda t: None))
    return L, parts


def test_the_panel_window_never_reaches_the_save_battery():
    """Box writes go to CartRAM, which the panel's allow predicate cannot even name (it speaks
    System Bus addresses). The refusal has to live at the cart door itself."""
    cart_writes: list[tuple[int, int, str]] = []
    L, parts = _entry_parts(cart_writes)
    box_io, writes = parts.box_io, parts.writes
    writes.arm(writes, "panel", parts.panel.allow)
    with pytest.raises(lupa.LuaError, match="cart write refused"):
        box_io.write_cart_bytes(0x100, L.table(1, 2))
    assert cart_writes == []
    writes.disarm(writes)
    writes.arm(writes, "overworld")
    box_io.write_cart_bytes(0x100, L.table(1, 2))
    assert cart_writes == [(0x100, 1, "CartRAM"), (0x101, 2, "CartRAM")]
