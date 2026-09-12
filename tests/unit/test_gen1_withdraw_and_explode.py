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
    lua.execute(f"bus[0xD163] = {slot + 1}")  # source-verified Red wPartyCount
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
    lua.execute(f"bus[{BOX_COUNT + 1}] = 0x99; bus[{BOX_COUNT + 2}] = 255")
    lua.execute("bus[0xD164] = 255")
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
    assert "incomplete stats block" in err, err


def test_partial_stats_block_is_refused():
    """maxHP without level (or vice versa) still leaves the struct half-written."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, _stats(lua, attack=30, defense=25))
    assert ok is False
    assert "incomplete stats block" in err, err


def test_absent_stats_is_reported_differently_from_unusable():
    """A cold client that never saw the deposit is a different failure from a server
    that sent a block it could not fill — a run log that conflates them sends whoever
    debugs it to the wrong side of the wire."""
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, None)
    assert ok is False
    assert "no cached stats" in err, err
    assert "incomplete" not in err


def test_the_level_and_maxhp_block_the_server_actually_sends_is_refused():
    """THE shape that got past the first version of this guard.

    server/state.py caches `{"level", "maxHP"}` for every Gen 1 capture -- the client's
    capture event carries those two as top-level fields and no stats block at all. A guard
    that asked only for maxHP and level therefore accepted it, applyPartyStats wrote those
    two, and Attack/Defence/Speed/Special stayed at the 0 the memzero left: the exact
    "silent, permanent save corruption" the refusal branch's own comment describes, arriving
    through the guard meant to prevent it.

    In this harness there is no ROM domain, so the cartridge rebuild cannot fire and the
    call must refuse. On a real cartridge the rebuild fires instead and returns exact stats
    -- proven by lua/tests/test_gen1_stat_rebuild.lua. Either way the mon never comes back
    with zeroed stats, which is the whole invariant.
    """
    lua, M = runtime()
    seed_boxed_mon(lua)
    ok, err = M.retrieveBoxMon(BOXED_KEY, _stats(lua, level=27, maxHP=89))
    assert ok is False, "a block with no fighting stats must not be accepted"
    assert "incomplete stats block" in err, err
    # And nothing half-written was left behind.
    assert byte(lua, PARTY_BASE + 0x21) == 0, "level was written despite the refusal"


def _attach_clean_rom(lua):
    path = os.path.join(REPO, "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb")
    with open(path, "rb") as file:
        rom = file.read()
    lua.globals().read_rom_byte = lambda address: rom[address]
    lua.execute("""local old = memory.read_u8
        memory.read_u8 = function(a, d) if d == "ROM" then return read_rom_byte(a) end return old(a, d) end
    """)


def test_complete_cache_is_validated_but_withdrawal_recomputes_from_experience():
    lua, M = runtime()
    seed_boxed_mon(lua)
    _attach_clean_rom(lua)
    lua.execute(f"bus[{BOX_BASE + 0x0F}] = 3; bus[{BOX_BASE + 0x10}] = 232")  # XP 1000
    lua.execute(f"bus[{BOX_BASE + 3}] = 90")  # deliberately stale BoxLevel
    result = M.retrieveBoxMon(BOXED_KEY, _stats(
        lua, level=27, maxHP=89, attack=31, defense=41, speed=51, spAtk=61, spDef=61))
    assert result is True
    # Bulbasaur medium-slow XP thresholds: L12=973, L13=1261. DV HP=3.
    assert byte(lua, PARTY_BASE + 0x21) == 12
    assert byte(lua, PARTY_BASE + 0x22) * 256 + byte(lua, PARTY_BASE + 0x23) == 33


@pytest.mark.parametrize("stats", [{}, {"level": 5}, {"level": 5, "maxHP": 2000,
    "attack": 10, "defense": 10, "speed": 10, "spAtk": 10}])
def test_rejected_stats_never_mutate_any_bus_or_cart_byte(stats):
    lua, M = runtime()
    seed_boxed_mon(lua)
    _attach_clean_rom(lua)
    lua.execute(f"for i=0,43 do bus[{PARTY_BASE}+i] = 0xA5 end")
    before = dict(lua.globals().bus), dict(lua.globals().cart)
    result = M.retrieveBoxMon(BOXED_KEY, _stats(lua, **stats))
    assert result[0] is False
    assert (dict(lua.globals().bus), dict(lua.globals().cart)) == before


def test_absent_cache_rebuilds_and_preserves_hp_status():
    lua, M = runtime()
    seed_boxed_mon(lua)
    _attach_clean_rom(lua)
    lua.execute(f"bus[{BOX_BASE + 1}] = 0; bus[{BOX_BASE + 2}] = 45; bus[{BOX_BASE + 4}] = 8")
    assert M.retrieveBoxMon(BOXED_KEY, None) is True
    assert byte(lua, PARTY_BASE + 0x21) == 1  # XP0, even if BoxLevel differs
    assert byte(lua, PARTY_BASE + 1) * 256 + byte(lua, PARTY_BASE + 2) == 45
    assert byte(lua, PARTY_BASE + 4) == 8


@pytest.mark.parametrize("value", [12, 127, 140, 255])
def test_invalid_current_box_refuses_deposit_and_retrieval_without_writes(value):
    lua, M = runtime()
    seed_boxed_mon(lua)
    lua.execute(f"bus[{int(M.CURRENT_BOX_NUM_ADDR)}] = {value}")
    before = dict(lua.globals().bus), dict(lua.globals().cart)
    assert M.getCurrentBoxNum() is None
    assert M.depositPartyMon(0)[0] is False
    assert M.retrieveBoxMon(BOXED_KEY, None)[0] is False
    assert M.storedBoxKeys()[0] is None
    assert (dict(lua.globals().bus), dict(lua.globals().cart)) == before


def _assert_storage_scan_sources(variant, current):
    lua, M = runtime(variant)
    bus, cart = lua.globals().bus, lua.globals().cart
    sb = M.profile.stored_boxes
    offsets = [int(sb.banks[index // 6 + 1]) + index % 6 * int(sb.stride)
               for index in range(12)]
    sram_keys = set()
    for index, offset in enumerate(offsets):
        # Every SRAM box has a valid, unique member. The currently selected
        # slot's member is intentionally stale: only its WRAM copy counts.
        cart[offset] = 1
        cart[offset + 1], cart[offset + 2] = 0x99, 255
        base = offset + 22
        cart[base], cart[base + 12], cart[base + 13] = 0x99, 0x12, index
        cart[base + 27], cart[base + 28] = 0xAA, 0xBB
        sram_keys.add(f"AABB:{0x1200 + index:04X}:99")
    bus[int(M.CURRENT_BOX_NUM_ADDR)] = 0x80 + current
    bus[int(M.BOX_COUNT_ADDR)] = 1
    bus[int(M.BOX_SPECIES_ADDR)], bus[int(M.BOX_SPECIES_ADDR) + 1] = 0x99, 255
    active = int(M.BOX_BASE_ADDR)
    bus[active], bus[active + 12], bus[active + 13] = 0x99, 0xEE, current
    bus[active + 27], bus[active + 28] = 0xCC, 0xDD
    active_key = f"CCDD:{0xEE00 + current:04X}:99"
    stale_key = f"AABB:{0x1200 + current:04X}:99"
    before = dict(bus), dict(cart)
    keys = M.storedBoxKeys()
    observed = set(keys.keys())
    assert observed == (sram_keys - {stale_key}) | {active_key}
    assert stale_key not in observed and len(observed) == 12
    assert (dict(bus), dict(cart)) == before
    # Poison an inactive source; a scanner accidentally reading only Box 12
    # or accepting WRAM as an SRAM substitute must now refuse the full scan.
    other = (current + 1) % 12
    cart[offsets[other] + 2] = 0
    result = M.storedBoxKeys()
    assert result[0] is None and result[1] == "invalid box species terminator"


def test_storage_scan_uses_wram_for_current_box_and_sram_for_other_eleven():
    for variant in ("red", "blue", "yellow"):
        for current in range(12):
            _assert_storage_scan_sources(variant, current)


def test_inactive_boxes_do_not_exist_before_first_changebox():
    lua, M = runtime()
    seed_boxed_mon(lua)
    lua.execute(f"bus[{int(M.BOX_SPECIES_ADDR)}] = 0x99; bus[{int(M.BOX_SPECIES_ADDR) + 1}] = 255")
    lua.execute("for i=0x4000,0x7FFF do cart[i] = 255 end")
    assert set(M.storedBoxKeys().keys()) == {BOXED_KEY}


def test_experience_levels_use_source_curve_boundaries():
    _, M = runtime()
    game = M._game
    assert game.levelFromExperience(3, 972) == 11
    assert game.levelFromExperience(3, 973) == 12
    assert game.levelFromExperience(3, 1260) == 12
    assert game.levelFromExperience(3, 1261) == 13
    assert game.levelFromExperience(4, 800000) == 100
    assert game.levelFromExperience(5, 1250000) == 100
    assert game.levelFromExperience(4, 800001) is None
    assert game.levelFromExperience(0, 0) == 1
    assert game.levelFromExperience(0, 2.5) is None


@pytest.mark.parametrize("location", ["current_box", "inactive_box", "party", "bad_list", "bad_terminator"])
def test_retrieval_requires_unambiguous_consistent_storage_before_writes(location):
    lua, M = runtime()
    seed_boxed_mon(lua)
    _attach_clean_rom(lua)
    bus, cart = lua.globals().bus, lua.globals().cart
    if location == "current_box":
        bus[BOX_COUNT] = 2
        bus[BOX_COUNT + 2], bus[BOX_COUNT + 3] = 0x99, 255
        for i in range(33):
            bus[BOX_BASE + 33 + i] = bus[BOX_BASE + i] or 0
    elif location == "inactive_box":
        bus[int(M.CURRENT_BOX_NUM_ADDR)] = 128
        for bank in (2, 3):
            for slot in range(6):
                cart[bank * 8192 + slot * 1122] = 0
                cart[bank * 8192 + slot * 1122 + 1] = 255
        cart[0x75EA], cart[0x75EB], cart[0x75EC] = 1, 0x99, 255
        for i in range(33):
            cart[0x7600 + i] = bus[BOX_BASE + i] or 0
    elif location == "party":
        bus[int(M.PARTY_COUNT_ADDR)] = 1
        bus[int(M.PARTY_SPECIES_ADDR)], bus[int(M.PARTY_SPECIES_ADDR) + 1] = 0x99, 255
        for i in range(33):
            bus[PARTY_BASE + i] = bus[BOX_BASE + i] or 0
    elif location == "bad_list":
        bus[BOX_COUNT + 1] = 0xB1
    else:
        bus[BOX_COUNT + 2] = 0
    before = dict(bus), dict(cart)
    assert M.retrieveBoxMon(BOXED_KEY, None)[0] is False
    assert (dict(bus), dict(cart)) == before


def _yellow_starter():
    lua, M = runtime("yellow")
    bus = lua.globals().bus
    p = M.profile
    bus[int(M.PARTY_COUNT_ADDR)], bus[int(M.BOX_COUNT_ADDR)] = 2, 0
    base = int(M.PARTY_BASE_ADDR)
    bus[base], bus[base + 44] = 84, 0x99
    bus[int(M.PARTY_SPECIES_ADDR)] = 84
    bus[int(M.PARTY_SPECIES_ADDR) + 1], bus[int(M.PARTY_SPECIES_ADDR) + 2] = 0x99, 255
    bus[int(M.BOX_SPECIES_ADDR)] = 255
    bus[base + 12], bus[base + 13] = 0x12, 0x34
    bus[int(M.PLAYER_ID_ADDR)], bus[int(M.PLAYER_ID_ADDR) + 1] = 0x12, 0x34
    for i in range(11):
        bus[int(M.PLAYER_NAME_ADDR) + i] = 0x50
        bus[int(M.PARTY_OT_NAMES_ADDR) + i] = 0x50
    bus[int(p.PIKACHU_HAPPINESS_ADDR)], bus[int(p.PIKACHU_MOOD_ADDR)] = 200, 200
    return lua, M


@pytest.mark.parametrize("happiness,expected", [(0, 0), (2, 0), (99, 96), (100, 97), (199, 196), (200, 195), (255, 250)])
def test_yellow_following_starter_deposit_applies_canonical_happiness(happiness, expected):
    lua, M = _yellow_starter()
    bus, p = lua.globals().bus, M.profile
    bus[int(p.PIKACHU_HAPPINESS_ADDR)] = happiness
    bus[int(p.PIKACHU_OVERWORLD_FLAGS_ADDR)] = 0  # Following enabled.
    assert M.depositPartyMon(0) is True
    assert bus[int(p.PIKACHU_HAPPINESS_ADDR)] == expected
    assert bus[int(p.PIKACHU_MOOD_ADDR)] == 98


@pytest.mark.parametrize("difference,allowed", [(None, False), ("otid", True), ("fifth_byte", True), ("sixth_byte", False)])
def test_yellow_sleeping_starter_restriction_matches_identity_loop(difference, allowed):
    lua, M = _yellow_starter()
    bus, p = lua.globals().bus, M.profile
    bus[int(p.PIKACHU_OVERWORLD_FLAGS_ADDR)] = 2
    if difference == "otid":
        bus[int(M.PARTY_BASE_ADDR) + 13] = 0x35
    elif difference == "fifth_byte":
        bus[int(M.PARTY_OT_NAMES_ADDR) + 4] = 0x80
    elif difference == "sixth_byte":
        bus[int(M.PARTY_OT_NAMES_ADDR) + 5] = 0x80
    before = dict(bus), dict(lua.globals().cart)
    result = M.depositPartyMon(0)
    if allowed:
        assert result is True
        assert bus[int(p.PIKACHU_HAPPINESS_ADDR)] == 200  # Not starter identity.
    else:
        assert result[0] is False
        assert "sleeping starter Pikachu" in result[1]
        assert (dict(bus), dict(lua.globals().cart)) == before


@pytest.mark.parametrize("variant", ["red_ap", "blue_ap"])
def test_ap_withdrawal_preserves_validated_cache_path_without_vanilla_rom_roots(variant):
    lua, M = runtime(variant)
    bus = lua.globals().bus
    base = int(M.BOX_BASE_ADDR)
    bus[int(M.BOX_COUNT_ADDR)] = 1
    bus[int(M.BOX_SPECIES_ADDR)], bus[int(M.BOX_SPECIES_ADDR) + 1] = 0x99, 255
    bus[int(M.PARTY_SPECIES_ADDR)] = 255
    for off, value in {0: 0x99, 1: 0, 2: 45, 12: 0x12, 13: 0x34, 27: 0xAA, 28: 0xBB}.items():
        bus[base + off] = value
    before = dict(bus), dict(lua.globals().cart)
    assert M.retrieveBoxMon(BOXED_KEY, None)[0] is False
    assert (dict(bus), dict(lua.globals().cart)) == before
    assert M.retrieveBoxMon(BOXED_KEY, _stats(lua, level=27, maxHP=89, attack=31,
        defense=41, speed=51, spAtk=61, spDef=61)) is True
    assert M.read_u16_be(int(M.PARTY_BASE_ADDR) + int(M.MAXHP_OFFSET)) == 89
