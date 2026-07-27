"""Rival Team Swap and Explode Mode on Gen 1 — pure RAM, no ROM patch.

Gen 3 needed the native companion patch for the rival swap because `gEnemyParty` is
encrypted and checksummed. Gen 1 has no encryption, no checksums and no ASLR: the enemy
party is a plaintext block at a fixed address, so the swap is a byte copy and Explosion is
a move-id write. Both features are therefore enabled by two adapter overrides and some Lua,
with no patched ROM anywhere in the picture.

What the engine actually reads, from pret/pokered `LoadEnemyMonData` (engine/battle/core.asm):
species (+0x00), current HP (+0x01), status (+0x04), moves (+0x08) and level (+0x21) all
come from the party struct we write. Stats and DVs do NOT — for a trainer battle the engine
recomputes them from the species header with fixed trainer DVs. So a swapped team fights at
the partner's levels with the partner's moves and HP, which is the feature; it is not a
byte-perfect clone of their mons, and this file records that on purpose.

These execute the REAL Lua against a simulated address space, because the failure mode is
writing to the wrong address, which no amount of Python mocking would catch.
"""
import os

import pytest

from server.adapters import get_adapter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_GB = os.path.join(REPO, "lua", "memory_gb.lua")
GEN1 = os.path.join(REPO, "lua", "games", "gen1_rby.lua")

# pret/pokered, verified by tools/verify_profile_addresses.py
ENEMY_COUNT, ENEMY_SPECIES, ENEMY_BASE = 0xD89C, 0xD89D, 0xD8A4
ENEMY_OT, ENEMY_NICKS = 0xD9AC, 0xD9EE
STRUCT = 44
LEVEL_OFF, HP_OFF, MOVES_OFF = 0x21, 0x01, 0x08
BATTLE_MON_MOVES, BATTLE_MON_PP = 0xD01C, 0xD02D
SELECTED_MOVE, MOVE_LIST_INDEX = 0xCCDC, 0xCC2E
IN_BATTLE = 0xD057
EXPLOSION = 153


@pytest.fixture
def mem():
    lupa = pytest.importorskip("lupa")
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("""
    _G.RAM = {}
    _G.memory = {
      getmemorydomainlist = function() return {"System Bus","CartRAM","ROM"} end,
      read_u8 = function(a) return RAM[a] or 0 end,
      write_u8 = function(a,v) RAM[a] = v end,
      read_u16_le = function(a) return (RAM[a] or 0) + 256*(RAM[a+1] or 0) end,
      write_u16_le = function(a,v) RAM[a]=v%256; RAM[a+1]=math.floor(v/256) end,
    }
    _G.console = { log = function() end }
    _G.print = function() end
    """)
    load = L.eval("function(s) return load(s)() end")
    with open(MEMORY_GB, encoding="utf-8") as f:
        M = load(f.read())
    with open(GEN1, encoding="utf-8") as f:
        G = load(f.read())
    M.initProfile(G, "red")
    return L, M


def _blob(species, level, hp, tag):
    """A 66-byte Gen 1 blob: 44-byte struct + 11 OT + 11 nickname."""
    b = [tag] * STRUCT
    b[0] = species
    b[HP_OFF] = hp >> 8
    b[HP_OFF + 1] = hp & 0xFF
    b[LEVEL_OFF] = level
    return b + [0xA0 + tag] * 11 + [0xB0 + tag] * 11


def _write(L, M, blobs):
    return M.writeEnemyParty(L.table_from([L.table_from(b) for b in blobs]))


# ── Rival Team Swap ────────────────────────────────────────────────────────────

def test_swap_writes_count_species_list_and_terminator(mem):
    L, M = mem
    ok, n = _write(L, M, [_blob(0x99, 42, 100, 1), _blob(0x15, 37, 55, 2)])
    R = L.globals().RAM
    assert (ok, n) == (True, 2)
    assert R[ENEMY_COUNT] == 2
    # The engine iterates the species LIST to pick the next mon; the copy inside each
    # struct is not enough on its own.
    assert [R[ENEMY_SPECIES], R[ENEMY_SPECIES + 1]] == [0x99, 0x15]
    assert R[ENEMY_SPECIES + 2] == 0xFF, "species list must be 0xFF-terminated"


def test_swap_places_each_mon_at_the_right_stride(mem):
    L, M = mem
    _write(L, M, [_blob(0x99, 42, 100, 1), _blob(0x15, 37, 55, 2)])
    R = L.globals().RAM
    for i, (species, level) in enumerate([(0x99, 42), (0x15, 37)]):
        base = ENEMY_BASE + i * STRUCT
        assert R[base] == species
        # Level at +0x21 is what send-out copies into wCurEnemyLevel.
        assert R[base + LEVEL_OFF] == level, f"mon {i} level landed at the wrong offset"


def test_swap_writes_the_parallel_name_arrays(mem):
    """Gen 1 keeps OT names and nicknames OUTSIDE the struct — miss these and the rival's
    team shows the previous trainer's names."""
    L, M = mem
    _write(L, M, [_blob(0x99, 42, 100, 1), _blob(0x15, 37, 55, 2)])
    R = L.globals().RAM
    assert R[ENEMY_OT] == 0xA1 and R[ENEMY_OT + 11] == 0xA2
    assert R[ENEMY_NICKS] == 0xB1 and R[ENEMY_NICKS + 11] == 0xB2


def test_swap_stays_inside_the_enemy_block(mem):
    """The whole region is 0x194 bytes from wEnemyPartyCount; a full 6-mon team must not
    run past it into whatever lives next."""
    L, M = mem
    _write(L, M, [_blob(0x10 + i, 20 + i, 40, i + 1) for i in range(6)])
    R = L.globals().RAM
    end_of_block = ENEMY_NICKS + 6 * 11
    assert all(R[a] is None for a in range(end_of_block, end_of_block + 16)), \
        "wrote past the end of the enemy party block"


def test_swap_caps_at_six_mons(mem):
    L, M = mem
    ok, n = _write(L, M, [_blob(0x10 + i, 20, 40, 1) for i in range(8)])
    assert (ok, n) == (True, 6)
    assert L.globals().RAM[ENEMY_COUNT] == 6


def test_swap_rejects_a_short_blob_rather_than_writing_garbage(mem):
    L, M = mem
    short = _blob(0x99, 42, 100, 1)[:40]
    ok, err = _write(L, M, [short])
    assert ok is False and "short" in str(err)


def test_swap_rejects_an_empty_team(mem):
    L, M = mem
    ok, err = _write(L, M, [])
    assert ok is False


# ── Explode Mode ───────────────────────────────────────────────────────────────

def test_explode_arms_the_active_battler(mem):
    L, M = mem
    L.globals().RAM[IN_BATTLE] = 1
    assert M.forceExplode(0) is True
    R = L.globals().RAM
    assert R[BATTLE_MON_MOVES] == EXPLOSION, "move slot 0 not overwritten"
    assert R[BATTLE_MON_PP] == 5, "PP must be nonzero or the engine refuses the move"
    assert R[SELECTED_MOVE] == EXPLOSION, "wPlayerSelectedMove is what the engine acts on"
    assert R[MOVE_LIST_INDEX] == 0, "selection index must point at the overwritten slot"


def test_explode_mirrors_into_the_party_struct(mem):
    """Otherwise a switch-out and back restores the mon's real move set."""
    L, M = mem
    L.globals().RAM[IN_BATTLE] = 1
    M.forceExplode(0)
    party_base = 0xD16B
    assert L.globals().RAM[party_base + MOVES_OFF] == EXPLOSION


def test_explode_refuses_outside_battle(mem):
    """No battler to coerce — the caller must fall back to a plain force_faint."""
    L, M = mem
    L.globals().RAM[IN_BATTLE] = 0
    ok, err = M.forceExplode(0)
    assert ok is False and "not in battle" in str(err)


def test_explosion_move_id_matches_pret(mem):
    """pret/pokered constants/move_constants.asm: EXPLOSION = $99."""
    _, M = mem
    assert int(M.MOVE_EXPLOSION) == 0x99 == 153


# ── Adapter gates ──────────────────────────────────────────────────────────────

def test_adapter_opts_into_both_features():
    a = get_adapter("gen1_rby", rom_type="Red")
    assert a.supports_explode_mode() is True
    # RIVAL1/2/3 = $19/$2A/$2B + OPP_ID_OFFSET(200).
    assert a.rival_trainer_ids() == {225, 242, 243}


def test_non_rival_trainers_do_not_trigger_a_swap():
    a = get_adapter("gen1_rby", rom_type="Red")
    for tid in (201, 234, 247):     # Youngster, Brock, Lance
        assert tid not in a.rival_trainer_ids()
