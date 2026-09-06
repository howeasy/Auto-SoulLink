"""Gen 1 must not mistake the title screen for a live game.

`validateROM`'s Gen 1 branch used to be a single check — `mapId > 0xF7` — which is
barely a gate at all: **party count 0 passes, and map 0 passes**, and map 0 is
Pallet Town, the fixture's own map. So uninitialised WRAM during the intro
validated as a running game and `writes_enabled` was turned on.

Gen 2's branch has carried a second test since its bring-up (`PLAYER_ID != 0`),
and Gen 1's profile has had `PLAYER_ID_ADDR` all along without using it. `wPlayerID`
is assigned from two unfiltered RNG bytes, so 0000 alone is not a pregame marker.
A matching valid save or a nonempty sane party must not be rejected for that ID.

The consequence this closes is not cosmetic. `send_hello` was the ONLY party-snapshot
caller in the client without a count gate, and the server locks
`player_identity[pid]["ot_id"]` from `party[0]`'s key on the first hello. Loading the
Lua script at the title screen — the normal thing to do — could latch a garbage OT,
after which every subsequent hello is rejected as WRONG SAVE and all events are
blocked until someone hand-edits `links.json`.
"""
import os
import re

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PLAYER_ID = {"red": 0xD359, "yellow": 0xD358}
MAP_ID = {"red": 0xD35E, "yellow": 0xD35D}
PARTY_COUNT = {"red": 0xD163, "yellow": 0xD162}
PARTY_SPECIES = {"red": 0xD164, "yellow": 0xD163}


def runtime(variant="red"):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("bus = {}; print = function() end")
    lua.execute("""
        memory = {
            getmemorydomainlist = function() return {"System Bus"} end,
            read_u8  = function(a, d) return bus[a] or 0 end,
            write_u8 = function(a, v, d) bus[a] = v % 256 end,
            read_u16_le = function(a, d) return (bus[a] or 0) + (bus[a+1] or 0) * 256 end,
            write_u16_le = function(a, v, d)
                bus[a] = v % 256; bus[a+1] = math.floor(v/256) % 256 end,
        }
    """)
    mem = os.path.join(REPO, "lua", "memory_gb.lua").replace("\\", "/")
    game = os.path.join(REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    M = lua.eval(f'dofile("{mem}")')
    G = lua.eval(f'dofile("{game}")')
    M.initProfile(G, variant)
    return lua, M


def set_player_id(lua, variant, value):
    a = PLAYER_ID[variant]
    lua.execute(f"bus[{a}] = {value // 256}; bus[{a + 1}] = {value % 256}")


@pytest.mark.parametrize("variant", ["red", "yellow"])
def test_pregame_zero_player_id_is_rejected(variant):
    """The exact title-screen state: everything zeroed, including map 0 = Pallet."""
    lua, M = runtime(variant)
    ok, why = M.validateROM()
    assert ok is False, "an all-zero WRAM must not validate as a live game"
    assert "Player ID" in why, why


@pytest.mark.parametrize("variant", ["red", "yellow"])
def test_a_real_save_still_validates(variant):
    """Load-bearing control: a gate that rejects everything would disable all writes."""
    lua, M = runtime(variant)
    set_player_id(lua, variant, 0x1234)
    lua.execute(f"bus[{MAP_ID[variant]}] = 0")      # Pallet Town, a legitimate map
    lua.execute(f"bus[{PARTY_COUNT[variant]}] = 3")
    # A non-zero count needs a real first species; validateROM already checks that.
    lua.execute(f"bus[{PARTY_SPECIES[variant]}] = 0x99")
    ok, why = M.validateROM()
    assert ok is True, f"a real save must still validate (rejected as {why!r})"


def test_map_zero_alone_was_never_enough():
    """Pins the reason the old single check was weak: map 0 is a REAL map."""
    lua, M = runtime("red")
    lua.execute(f"bus[{MAP_ID['red']}] = 0")
    ok, why = M.validateROM()
    assert ok is False and "Player ID" in why, (
        "map 0 (Pallet Town) passes the map-range check, so it cannot be the only gate")


def test_out_of_range_map_still_rejected():
    lua, M = runtime("red")
    set_player_id(lua, "red", 0x1234)
    lua.execute(f"bus[{MAP_ID['red']}] = 0xF8")
    ok, why = M.validateROM()
    assert ok is False and "Map ID" in why, why


# ── the hello gate ───────────────────────────────────────────────────────

def test_send_hello_gates_its_party_snapshot():
    """Every other snapshot caller gates on the count; hello is where it matters most,
    because the server latches the identity lock from the first hello it receives."""
    path = os.path.join(REPO, "lua", "clients", "gen1_rby_client.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"local function send_hello\(\)(.*?)local cur_in_battle", src, flags=re.S)
    assert m, "could not find send_hello"
    body = m.group(1)
    assert re.search(r"<=\s*6", body), (
        "send_hello builds its party snapshot without a party-count gate; garbage at "
        "the title screen can poison the server's identity lock permanently")


@pytest.mark.parametrize("variant", ["red", "yellow"])
def test_zero_player_id_with_a_real_party_is_not_rejected_as_pregame(variant):
    lua, M = runtime(variant)
    lua.execute(f"bus[{PARTY_COUNT[variant]}] = 1; bus[{PARTY_SPECIES[variant]}] = 0x99")
    ok, reason = M.validateROM()
    assert ok is True, reason
