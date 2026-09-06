"""force_faint must reach the ACTIVE battler, not just the party struct.

WHY THIS EXISTS. Faint propagation is the core Soul Link rule, and on Gen 1 it did
not apply to the mon that was actually out. pokered's main battle loop is:

    MainInBattleLoop:
        call ReadPlayerMonCurHPAndStatus      ; engine/battle/core.asm:280
        ld hl, wBattleMonHP
        ld a, [hli] / or [hl] / jp z, HandlePlayerMonFainted

and `ReadPlayerMonCurHPAndStatus` (`:1798-1809`) copies wBattleMonHP *into* the
party struct — its own comment says "so it stays after battle or switching". The
data flows battle -> party, so `M.forceFaint`'s party-only write was overwritten at
the top of the next turn and never read. Your partner's mon died, the toast fired,
and your linked mon kept fighting at full HP.

WHY NO EXISTING TEST CAUGHT IT. The `faint` duo scenario stages a battle by poking
`wIsInBattle` directly, so `MainInBattleLoop` never runs and nothing ever overwrites
the party struct — the assertion passed precisely because the engine was absent.
These tests drive the REAL `lua/memory_gb.lua` and the REAL `lua/games/gen1_rby.lua`
through `initProfile`, because the defect was a wiring gap as much as a logic one:
an address declared in the profile but never copied by `initProfile` is a no-op.
"""
import os

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pret: wBattleMonHP is 0xD015 in Red/Blue and 0xD014 in Yellow (the 0xD0xx block
# carries Yellow's -1 shift; the 0xCCxx block does not).
BATTLE_MON_HP = {"red": 0xD015, "blue": 0xD015, "yellow": 0xD014}
PARTY_BASE = {"red": 0xD16B, "blue": 0xD16B, "yellow": 0xD16A}
BATTLE_FLAG = {"red": 0xD057, "blue": 0xD057, "yellow": 0xD056}
PLAYER_MON_NUMBER = 0xCC2F          # not shifted in Yellow
PARTY_STRUCT = 44
HP_OFFSET = 0x01


def runtime(variant="red"):
    """Real memory_gb + real gen1_rby profiles over a flat fake System Bus."""
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
    lua.globals().bus[M.PARTY_COUNT_ADDR] = 3  # valid slots 0..2 in this controlled party
    return lua, M


def poke(lua, addr, val):
    lua.execute(f"bus[{addr}] = {val}")


def peek16be(lua, addr):
    return lua.eval(f"(bus[{addr}] or 0) * 256 + (bus[{addr}+1] or 0)")


def arm_battle(lua, variant, *, active_slot, battle_hp=57, in_battle=1):
    poke(lua, BATTLE_FLAG[variant], in_battle)
    poke(lua, PLAYER_MON_NUMBER, active_slot)
    lua.execute(f"bus[{BATTLE_MON_HP[variant]}] = {battle_hp // 256}")
    lua.execute(f"bus[{BATTLE_MON_HP[variant] + 1}] = {battle_hp % 256}")


def party_hp(lua, variant, slot):
    return peek16be(lua, PARTY_BASE[variant] + slot * PARTY_STRUCT + HP_OFFSET)


def set_party_hp(lua, variant, slot, hp):
    addr = PARTY_BASE[variant] + slot * PARTY_STRUCT + HP_OFFSET
    lua.execute(f"bus[{addr}] = {hp // 256}; bus[{addr + 1}] = {hp % 256}")


# ── the wiring gap ───────────────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_initprofile_copies_the_battle_hp_address(variant):
    """Declaring it in the profile is not enough — initProfile copies each field
    explicitly, so a missing line there makes the whole fix a silent no-op."""
    _, M = runtime(variant)
    got = M.BATTLE_MON_HP_ADDR
    assert got == BATTLE_MON_HP[variant], (
        f"{variant}: initProfile did not copy BATTLE_MON_HP_ADDR (got {got!r})")


# ── the behaviour ────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_active_battler_is_killed_in_the_battle_struct(variant):
    lua, M = runtime(variant)
    set_party_hp(lua, variant, 2, 40)
    arm_battle(lua, variant, active_slot=2, battle_hp=57)

    assert M.forceFaint(2) is True, "should report that it wrote the battle struct"
    assert peek16be(lua, BATTLE_MON_HP[variant]) == 0, (
        "wBattleMonHP is what MainInBattleLoop reads; leaving it non-zero means the "
        "mon keeps fighting and the party write is overwritten next turn")
    assert party_hp(lua, variant, 2) == 0, "the party struct must still be zeroed too"


def test_benched_mon_does_not_touch_the_battle_struct():
    """Slot 0 is linked and dies while slot 2 is out — zeroing wBattleMonHP would
    kill the WRONG mon, the one the player is currently using."""
    lua, M = runtime("red")
    set_party_hp(lua, "red", 0, 31)
    arm_battle(lua, "red", active_slot=2, battle_hp=57)

    assert M.forceFaint(0) is False
    assert party_hp(lua, "red", 0) == 0
    assert peek16be(lua, BATTLE_MON_HP["red"]) == 57, "active battler must be untouched"


def test_out_of_battle_does_not_touch_the_battle_struct():
    lua, M = runtime("red")
    set_party_hp(lua, "red", 0, 31)
    arm_battle(lua, "red", active_slot=0, battle_hp=57, in_battle=0)

    assert M.forceFaint(0) is False
    assert party_hp(lua, "red", 0) == 0
    assert peek16be(lua, BATTLE_MON_HP["red"]) == 57


def test_in_battle_lost_sentinel_is_not_in_battle():
    """wIsInBattle == 0xFF is the post-battle/blackout sentinel, not a live battle."""
    lua, M = runtime("red")
    set_party_hp(lua, "red", 0, 31)
    arm_battle(lua, "red", active_slot=0, battle_hp=57, in_battle=0xFF)

    assert M.forceFaint(0) is False
    assert peek16be(lua, BATTLE_MON_HP["red"]) == 57


@pytest.mark.parametrize("flag", [1, 2])
def test_both_wild_and_trainer_battles_count(flag):
    lua, M = runtime("red")
    arm_battle(lua, "red", active_slot=0, battle_hp=57, in_battle=flag)
    assert M.forceFaint(0) is True
    assert peek16be(lua, BATTLE_MON_HP["red"]) == 0


# ── the inheritance hazard ───────────────────────────────────────────────

def test_archipelago_inherits_the_address_because_it_did_not_move():
    """This test used to assert the OPPOSITE, on a false premise.

    It said the Alchav fork "relocates the 0xD0xx block", so BATTLE_MON_HP_ADDR was
    disowned for red_ap/blue_ap. data/pret_syms.json disagrees: the fork gives
    wBattleMonHP 0xD015, exactly Red's value, and of the 155 symbols the two checkouts
    share in 0xD000-0xD0FF not one differs. The relocation starts higher (wPlayerID
    0xD359 -> 0xD431). So force_faint was left a no-op against the active battler on every
    AP cartridge for no reason, and a test enshrined it.

    The inheritance hazard is real and stays real -- see AP_UNVERIFIED, which still
    disowns STATUS_FLAGS_4_ADDR because the fork has no such symbol at all. The rule is
    per address, verified, not per block, assumed.
    """
    for variant in ("red_ap", "blue_ap"):
        _, M = runtime(variant)
        assert M.BATTLE_MON_HP_ADDR == 0xD015, (
            f"{variant} should inherit BATTLE_MON_HP_ADDR: the AP fork puts wBattleMonHP "
            f"at the same 0xD015 as vanilla")


def test_the_inheritance_hazard_is_still_enforced_where_it_is_real():
    """The control for the change above: a field the fork genuinely does not have must
    still be disowned rather than guessed."""
    for variant in ("red_ap", "blue_ap"):
        _, M = runtime(variant)
        assert not M.STATUS_FLAGS_4_ADDR, (
            f"{variant} inherited STATUS_FLAGS_4_ADDR; the Alchav fork has no "
            f"wStatusFlags4 symbol at all, so Red's 0xD72E would be a guess")


def test_archipelago_faints_the_active_battler_too():
    """The point of restoring the address: the in-battle fix now applies to AP as well."""
    lua, M = runtime("red_ap")
    arm_battle(lua, "red", active_slot=0, battle_hp=57)
    assert M.forceFaint(0) is True
    assert peek16be(lua, BATTLE_MON_HP["red"]) == 0


@pytest.mark.parametrize("variant", ["red", "blue", "yellow", "red_ap", "blue_ap"])
@pytest.mark.parametrize("method", ["forceFaint", "forceExplode"])
@pytest.mark.parametrize("count", [0, 7, 255])
def test_invalid_party_count_never_writes_any_hp_move_or_control_byte(variant, method, count):
    lua, memory = runtime(variant)
    arm_battle(lua, "yellow" if variant == "yellow" else "red", active_slot=0)
    lua.globals().bus[memory.PARTY_COUNT_ADDR] = count
    before = dict(lua.globals().bus)
    ok, reason = memory[method](0)
    assert ok is False and reason
    assert dict(lua.globals().bus) == before


@pytest.mark.parametrize("variant", ["red", "blue", "yellow", "red_ap", "blue_ap"])
@pytest.mark.parametrize("method", ["forceFaint", "forceExplode"])
@pytest.mark.parametrize("slot", [None, -1, 3, 6, 1.5, "0"])
def test_invalid_slot_never_writes_before_rejecting(variant, method, slot):
    lua, memory = runtime(variant)
    arm_battle(lua, "yellow" if variant == "yellow" else "red", active_slot=0)
    before = dict(lua.globals().bus)
    ok, reason = memory[method](slot)
    assert ok is False and reason
    assert dict(lua.globals().bus) == before


@pytest.mark.parametrize("method", ["forceFaint", "forceExplode"])
def test_invalid_active_index_cannot_cause_a_partial_write(method):
    lua, memory = runtime("red")
    arm_battle(lua, "red", active_slot=255)
    before = dict(lua.globals().bus)
    ok, reason = memory[method](0)
    assert ok is False and reason
    assert dict(lua.globals().bus) == before


def test_explode_cannot_target_a_benched_slot():
    lua, memory = runtime("red")
    arm_battle(lua, "red", active_slot=0)
    before = dict(lua.globals().bus)
    ok, reason = memory.forceExplode(1)
    assert ok is False and "active" in reason
    assert dict(lua.globals().bus) == before
