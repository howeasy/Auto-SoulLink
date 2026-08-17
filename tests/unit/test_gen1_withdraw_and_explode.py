"""Two Gen 1 defects that only a behavioural test can see.

**An empty stats block corrupted a withdrawn mon.** `server.py` queues
`{"cmd": "party_mon", ..., "stats": s.mon_stats.get(key, {})}` unconditionally, and
`{}` is a *truthy* table in Lua. So the empty block sailed past `retrieveBoxMon`'s
cache check, `applyPartyStats` matched none of its `if stats.X` branches and wrote
nothing, the `memzero` of the 44-byte party struct stood, and the refusal branch —
whose own comment says "silent, permanent save corruption" — was skipped. The mon
came back with maxHP 0 and every stat 0, then disappeared from the party snapshot
(which filters on `maxHP > 0`) while still occupying a slot.

**Explode Mode was escapable.** `forceExplode` wrote Explosion into move slot 0
only, but the engine re-derives the chosen move from the slot the player confirms:

    add hl, bc                                  ; wBattleMonMoves + wCurrentMenuItem
    ld a, [hl] / ld [wPlayerSelectedMove], a    ; engine/battle/core.asm:2664-2668

so picking the second, third or fourth move used the mon's real move and the
coercion silently did not happen. The duo scenario could not catch it: it stages
`wIsInBattle` by poking, so the engine never consumes the write at all.
"""
import os

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXPLOSION = 153
BATTLE_MON_MOVES = 0xD01C      # red
BATTLE_MON_PP = 0xD02D
BATTLE_FLAG = 0xD057
PLAYER_MON_NUMBER = 0xCC2F
PARTY_BASE = 0xD16B
PARTY_STRUCT = 44
MOVES_OFFSET = 0x08
PP_OFFSET = 0x1D


def runtime(variant="red"):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("bus = {}; cart = {}; print = function() end")
    lua.execute("""
        local function pick(d)
            if d == "CartRAM" then return cart else return bus end
        end
        memory = {
            getmemorydomainlist = function() return {"System Bus", "CartRAM"} end,
            read_u8  = function(a, d) return pick(d)[a] or 0 end,
            write_u8 = function(a, v, d) pick(d)[a] = v % 256 end,
            read_u16_le = function(a, d) local t = pick(d)
                                         return (t[a] or 0) + (t[a+1] or 0) * 256 end,
            write_u16_le = function(a, v, d) local t = pick(d)
                                             t[a] = v % 256; t[a+1] = math.floor(v/256) % 256 end,
        }
    """)
    mem = os.path.join(REPO, "lua", "memory_gb.lua").replace("\\", "/")
    game = os.path.join(REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    M = lua.eval(f'dofile("{mem}")')
    G = lua.eval(f'dofile("{game}")')
    M.initProfile(G, variant)
    return lua, M


def byte(lua, addr):
    return lua.eval(f"bus[{addr}] or 0")


# ── Explode Mode ─────────────────────────────────────────────────────────

def _arm_battle(lua, slot=0):
    lua.execute(f"bus[{BATTLE_FLAG}] = 1")
    lua.execute(f"bus[{PLAYER_MON_NUMBER}] = {slot}")


def test_explode_fills_every_battle_move_slot():
    """Any move the player picks must resolve to Explosion."""
    lua, M = runtime()
    _arm_battle(lua)
    for i in range(4):
        lua.execute(f"bus[{BATTLE_MON_MOVES + i}] = {33 + i}")   # four real moves

    assert M.forceExplode(0) is True
    for i in range(4):
        assert byte(lua, BATTLE_MON_MOVES + i) == EXPLOSION, (
            f"battle move slot {i} still holds a real move — the engine re-derives "
            f"wPlayerSelectedMove from the slot the player confirms, so picking "
            f"slot {i} escapes Explode Mode entirely")


def test_explode_gives_every_slot_pp():
    """A slot with 0 PP is refused by the engine, which would reopen the escape."""
    lua, M = runtime()
    _arm_battle(lua)
    M.forceExplode(0)
    for i in range(4):
        assert byte(lua, BATTLE_MON_PP + i) == 5, f"PP slot {i} not set"


def test_explode_mirrors_all_four_slots_into_the_party_struct():
    """Otherwise a switch-out/in restores the real moves and the coercion is undone."""
    lua, M = runtime()
    _arm_battle(lua, slot=2)
    M.forceExplode(2)
    base = PARTY_BASE + 2 * PARTY_STRUCT
    for i in range(4):
        assert byte(lua, base + MOVES_OFFSET + i) == EXPLOSION
        assert byte(lua, base + PP_OFFSET + i) == 5


def test_explode_refuses_outside_battle():
    lua, M = runtime()
    lua.execute(f"bus[{BATTLE_FLAG}] = 0")
    ok, err = M.forceExplode(0)
    assert ok is False
    assert "not in battle" in err


# ── the withdraw stats guard ─────────────────────────────────────────────

BOX_COUNT = 0xDA80
BOX_BASE = 0xDA96
BOX_STRUCT = 33
SPECIES_OFFSET = 0x00
OTID_OFFSET = 0x0C
DV1_OFFSET = 0x1B
DV2_OFFSET = 0x1C

# Matches memory_gb's monKey format "%02X%02X:%04X:%02X".
BOXED_KEY = "AABB:1234:99"


def _stats(lua, **kw):
    return lua.table_from(kw)


def seed_boxed_mon(lua):
    """Put one real mon in box slot 0 so retrieveBoxMon reaches the stats guard.

    Without this the call short-circuits on "not found in box" and the guard under
    test never runs — a green test that proves nothing.
    """
    lua.execute(f"bus[{BOX_COUNT}] = 1")
    lua.execute(f"bus[{BOX_BASE + SPECIES_OFFSET}] = 0x99")
    lua.execute(f"bus[{BOX_BASE + DV1_OFFSET}] = 0xAA")
    lua.execute(f"bus[{BOX_BASE + DV2_OFFSET}] = 0xBB")
    lua.execute(f"bus[{BOX_BASE + OTID_OFFSET}] = 0x12")
    lua.execute(f"bus[{BOX_BASE + OTID_OFFSET + 1}] = 0x34")


def test_the_fixture_actually_finds_the_mon():
    """Control for the three tests below: if the key does not resolve, they would
    all 'pass' on 'not found in box' without ever reaching the guard."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    assert M.scanBoxForKey(BOXED_KEY) == 0


def test_empty_stats_block_is_refused():
    """`{}` is truthy in Lua — this is the exact payload server.py sends when a key
    was never cached, and it used to reach applyPartyStats and write nothing."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, _stats(lua))
    assert ok is False
    assert "unusable stats block" in err, err


def test_partial_stats_block_is_refused():
    """maxHP without level (or vice versa) still leaves the struct half-written."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, _stats(lua, attack=30, defense=25))
    assert ok is False
    assert "unusable stats block" in err, err


def test_absent_stats_is_reported_differently_from_unusable():
    """A cold client that never saw the deposit is a different failure from a server
    that sent a block it could not fill — a run log that conflates them sends whoever
    debugs it to the wrong side of the wire."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, None)
    assert ok is False
    assert "no cached stats" in err, err
    assert "unusable" not in err


def test_a_usable_stats_block_still_succeeds():
    """The load-bearing control. Three "refuses" above would all pass against a
    guard that rejected everything, which would break party sync completely."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    # The success path returns a bare `true`; only failures return (false, reason).
    result = M.retrieveBoxMon(BOXED_KEY, _stats(
        lua, level=27, maxHP=89, attack=31, defense=41, speed=51, spAtk=61, spDef=61))
    assert result is True, f"a complete stats block must be accepted (got {result!r})"

    # And it must land in the party: maxHP at the party-only tail (+0x22).
    party0 = PARTY_BASE
    maxhp = byte(lua, party0 + 0x22) * 256 + byte(lua, party0 + 0x23)
    assert maxhp == 89, f"maxHP not restored into the party struct (got {maxhp})"
    assert byte(lua, party0 + 0x21) == 27, "level not restored"
