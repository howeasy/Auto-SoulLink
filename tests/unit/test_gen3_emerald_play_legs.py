"""lua/tests/gen3_scripted_play.lua's EMERALD_LEGS table (card E2-PLAY-PREP).

Pure-Lua checks through lupa (no emulator), same shape as test_gen3_scripted_play.py: the
module's top-level code only builds tables when SLINK_GEN3_TITLE=emerald (closures aren't
called), so it loads with SLINK_ROOT/SLINK_GEN3_TITLE set and nothing else stubbed. This does
NOT run any leg; it checks:

  1. every leg's `exercises` kinds are real Emerald site kinds
     (data/games/gen3_emerald/engine_signals.json), and the 12 target kinds (battle_begin,
     battle_end, faint, capture_wild, mon_given, whiteout, map_load, pc_deposit, pc_withdraw,
     pc_box_place, pc_release, save -- "pc_move" from the card expands to its four sub-kinds)
     are covered somewhere (open or not);
  2. every group-starting leg's `check(...)` literal (group, num, x, y) matches that group's own
     fixture tile, straight from tests/fixtures/gen3/README.md's own committed facts;
  3. every tile this driver actually walks onto or starts a group at (the grass-loop square, the
     Calvin approach tile, the two group start tiles) is passable per the pret layout collision
     grid, read straight from the ROM by tools/gba_map.py's Emerald support (this same card's own
     additive fix -- Tileset.metatileAttributes is u16@0x10 in pokeemerald, not FR/LG's u32@0x14).
     Skips cleanly when the Emerald ROM is not present on this machine.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_scripted_play.lua")
with open(_SCRIPT, encoding="utf-8") as _f:
    _SCRIPT_SRC = _f.read()

_ENGINE_SIGNALS = os.path.join(_REPO, "data", "games", "gen3_emerald", "engine_signals.json")
_ROM = os.path.join(_REPO, "patch", "build",
                     "gen3_Pokemon_-_Emerald_Version_(USA,_Europe).gba")
_EMERALD_GROUPS_ADDR = 0x08486578  # pokeemerald.sym gMapGroups (test_gen3_title_syms.py pins the .sym-derived value)

_SYMS_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_title_syms.lua")
sys.path.insert(0, os.path.join(_REPO, "tools"))
import gba_map  # noqa: E402

# The 9 kinds the worker card names, with "pc_move" expanded to its 4 real engine-signal kinds
# (data/games/gen3_emerald/engine_signals.json has no bare "pc_move" for a deposit/withdraw/
# box_place/release split -- gen3_scripted_play.lua's own FR pc legs already exercise the split
# kinds this same way, e.g. viridian_pc_deposit_withdraw's `pc_deposit`/`pc_withdraw`).
_REQUIRED_MIN_COVERAGE = {
    "battle_begin", "battle_end", "faint", "capture_wild", "mon_given", "whiteout", "map_load",
    "pc_deposit", "pc_withdraw", "pc_box_place", "pc_release", "save",
}

# tests/fixtures/gen3/README.md "emerald_{town,battle,trainer}.sav" table -- the committed,
# built-and-boot-checked facts this driver's `check(cp)` guards must agree with.
_FIXTURE_TILES = {
    "town":    (0, 10, 6, 17),   # Oldale Town heal tile, one Up step into the PC door
    "battle":  (0, 17, 21, 16),  # Route 102 tall grass
    "trainer": (0, 17, 32, 16),  # Route 102, one Right step into Calvin's sight
}

_LEG_MARKER = "EMERALD_LEGS[#EMERALD_LEGS + 1] = {"
_LEG_NAME = re.compile(r'name = "(?P<name>emerald_\w+)"')
_CHECK_CALL = re.compile(
    r'check = emerald_at\((?P<g>\d+), (?P<n>\d+), (?P<x>\d+), (?P<y>\d+)[,)]')


def _leg_chunks(src):
    """One text chunk per `EMERALD_LEGS[#EMERALD_LEGS + 1] = { ... }` literal, split on the
    marker itself so a later leg's own `check = emerald_at(...)` can never be attributed to an
    earlier leg that has none (a plain lazy-DOTALL regex across the whole file does exactly
    that -- caught by this test itself before this splitting was added)."""
    parts = src.split(_LEG_MARKER)[1:]  # part 0 is everything before the first leg
    for part in parts:
        end = part.find("\n}")
        yield part[:end] if end != -1 else part


@pytest.fixture(scope="module")
def lua():
    return LuaRuntime(unpack_returned_tuples=True)


@pytest.fixture(scope="module")
def module(lua):
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    os.environ["SLINK_GEN3_TITLE"] = "emerald"
    try:
        return lua.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    finally:
        del os.environ["SLINK_GEN3_TITLE"]


@pytest.fixture(scope="module")
def legs(module):
    return module.EMERALD_LEGS


@pytest.fixture(scope="module")
def emerald_kinds():
    with open(_ENGINE_SIGNALS, encoding="utf-8") as f:
        data = json.load(f)
    return set(data["titles"]["emerald"]["artifacts"]["clean"]["sites"].keys())


def _py_list(lua_table):
    return [lua_table[i] for i in range(1, len(lua_table) + 1)]


def _require_rom():
    if not os.path.exists(_ROM):
        pytest.skip(f"Emerald ROM not present: {_ROM}")


# ── 1. the module loads and the table has the shape the card asked for ─────────────────────────

def test_the_script_loads_with_title_emerald_without_running_any_leg(legs):
    assert len(legs) >= 9


def test_default_title_still_builds_an_empty_emerald_legs_table(lua):
    """A non-emerald load (the default TITLE="firered") must not pick up any of this card's
    legs -- EMERALD_LEGS is declared for every title but only POPULATED inside the `if TITLE ==
    "emerald"` guard (see gen3_scripted_play.lua's own comment on that declaration)."""
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    os.environ.pop("SLINK_GEN3_TITLE", None)
    mod = lua.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    assert len(mod.EMERALD_LEGS) == 0
    assert len(mod.LEGS) >= 9  # the FR/LG/RR table is unaffected


# ── 2. every leg names only real Emerald site kinds, and the 12 target kinds are covered ───────

def test_every_leg_names_at_least_one_real_emerald_site_kind(legs, emerald_kinds):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        name = leg["name"]
        kinds = _py_list(leg["exercises"])
        assert kinds, f"leg {name!r} names no site kinds"
        unknown = [k for k in kinds if k not in emerald_kinds]
        assert not unknown, (
            f"leg {name!r} names kind(s) {unknown} not in "
            f"data/games/gen3_emerald/engine_signals.json"
        )


def test_the_12_target_kinds_are_covered_somewhere_in_the_union(legs):
    covered = set()
    for i in range(1, len(legs) + 1):
        covered |= set(_py_list(legs[i]["exercises"]))
    missing = _REQUIRED_MIN_COVERAGE - covered
    assert not missing, f"no leg (open or not) exercises {missing}"


def test_open_legs_carry_a_reason(legs):
    saw_open = False
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["open"]:
            saw_open = True
            assert leg["open_reason"], f"leg {leg['name']!r} is open with no reason"
    assert saw_open


def test_pinned_legs_are_not_open(legs):
    """The 5 legs with a real run(): entering the PC, saving, the two battles, and the catch
    (card E2-CATCH-LEG turned emerald_route102_catch from OPEN into a real leg)."""
    pinned = {
        "emerald_enter_pc", "emerald_save_town", "emerald_route102_wild_battle",
        "emerald_calvin_trainer_battle", "emerald_route102_catch",
    }
    seen_not_open = set()
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["name"] in pinned:
            assert not leg["open"], f"leg {leg['name']!r} should be pinned, not open"
            seen_not_open.add(leg["name"])
    assert seen_not_open == pinned, f"missing pinned legs: {pinned - seen_not_open}"


# ── 3. every group-starting leg's check() literal matches that group's own fixture tile ────────

def test_group_start_checks_match_the_committed_fixture_tiles():
    found = {}
    for chunk in _leg_chunks(_SCRIPT_SRC):
        nm = _LEG_NAME.search(chunk)
        ck = _CHECK_CALL.search(chunk)
        if nm and ck:
            found[nm.group("name")] = tuple(int(v) for v in ck.groups())
    assert found, "no `check = emerald_at(...)` call found in any EMERALD_LEGS entry"
    expected = {
        "emerald_enter_pc": _FIXTURE_TILES["town"],
        "emerald_route102_wild_battle": _FIXTURE_TILES["battle"],
        "emerald_calvin_trainer_battle": _FIXTURE_TILES["trainer"],
        "emerald_route102_faint": _FIXTURE_TILES["battle"],  # emerald_lowhp.sav: same tile
    }
    for name, want in expected.items():
        assert name in found, f"leg {name!r} carries no check = emerald_at(...)"
        assert found[name] == want, (
            f"leg {name!r} checks {found[name]}, but tests/fixtures/gen3/README.md's own "
            f"tile is {want}"
        )


# ── 4. every tile this driver walks onto or starts at is passable, read from the ROM ───────────

def test_every_walked_or_start_tile_is_passable_per_the_pret_layout():
    _require_rom()
    rom = gba_map.load(_ROM, groups_addr=_EMERALD_GROUPS_ADDR, game="emerald")

    town = rom.map(0, 10)
    assert town.collision[17][6] == 0, "Oldale Town start tile (6,17) is not passable"

    route102 = rom.map(0, 17)
    grass_loop = [(21, 16), (22, 16), (22, 17), (21, 17)]
    for x, y in grass_loop:
        assert route102.collision[y][x] == 0, f"Route 102 grass-loop tile ({x},{y}) is not passable"
        assert route102.behaviour[y][x] == gba_map.MB_TALL_GRASS, (
            f"Route 102 grass-loop tile ({x},{y}) is not MB_TALL_GRASS"
        )
    for x, y in [(32, 16), (33, 16)]:
        assert route102.collision[y][x] == 0, f"Route 102 trainer tile ({x},{y}) is not passable"
    blocked_npc = {(o.x, o.y) for o in route102.objects}
    assert (33, 16) not in blocked_npc, "Calvin's sight tile (33,16) is occupied by an object event"


def test_oldale_pc_door_and_landing_tile_are_where_this_driver_expects():
    _require_rom()
    rom = gba_map.load(_ROM, groups_addr=_EMERALD_GROUPS_ADDR, game="emerald")
    town = rom.map(0, 10)
    door = next((w for w in town.warps if (w.x, w.y) == (6, 16)), None)
    assert door is not None, "no warp at Oldale Town (6,16)"
    assert (door.map_group, door.map_num) == (2, 2), (
        f"Oldale Town's (6,16) door leads to {door.map_group}.{door.map_num}, not "
        f"OldaleTown_PokemonCenter_1F (2.2)"
    )
    pc = rom.map(2, 2)
    assert pc.warps, "OldaleTown_PokemonCenter_1F (2.2) has no warps"
    landing = pc.warps[0]
    assert (landing.x, landing.y) == (7, 8), (
        f"PC landing tile is ({landing.x},{landing.y}), not the (7,8) this driver's "
        f"emerald_enter_pc leg verifies"
    )


# -- 5. card E2-CATCH-LEG: the catch leg is real, and the throw helper obeys its hard rules ------


def test_route102_catch_is_no_longer_open_and_exercises_capture_wild(legs):
    """The card's own target: emerald_route102_catch used to be OPEN (no bag pocket/cursor
    struct); E2-CATCH-LEG resolved gBagPosition/gBagMenu and this must now be a real leg."""
    found = None
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["name"] == "emerald_route102_catch":
            found = leg
            break
    assert found is not None, "emerald_route102_catch leg not found"
    assert not found["open"], "emerald_route102_catch: still OPEN"
    assert "capture_wild" in _py_list(found["exercises"])


def _function_body(name):
    """Slice out one `local function NAME(...) ... end` block, from the definition line to the
    matching UNINDENTED `end` (this file's own convention: a top-level function's closing `end`
    is flush left, every nested block's `end` is indented) -- robust against the function's own
    body containing nested `if`/`for` blocks that also close with `end`."""
    start = re.search(rf'local function {re.escape(name)}\(', _SCRIPT_SRC)
    assert start, f"function {name} not found"
    close = re.search(r'^end$', _SCRIPT_SRC[start.start():], re.M)
    assert close, f"function {name}: no flush-left closing end found"
    return _SCRIPT_SRC[start.start():start.start() + close.end()]


def test_emerald_throw_ball_never_sends_select():
    """Hard rule (card E2-CATCH-LEG, research note): SELECT swaps items in battle -- the helper
    must never send it. A source-level assertion, not an emulator run."""
    body = _function_body("emerald_throw_ball")
    assert not re.search(r'"Select"', body, re.I), (
        "emerald_throw_ball sends a Select press -- forbidden (it swaps items in battle)"
    )
    assert not re.search(r'Select\s*=\s*true', body, re.I), (
        "emerald_throw_ball sets Select=true directly -- forbidden"
    )


def test_emerald_throw_ball_steers_the_pocket_by_value_not_by_counting():
    """Hard rule: steer by reading gBagPosition.pocket until it equals BALLS_POCKET, never by
    counting presses (the pocket switch WRAPS, so a fixed press count can silently land on the
    wrong pocket). Source-level evidence: the pocket-switch loop reads the live value both before
    and after each press, and the final check re-reads it rather than trusting the loop counter."""
    body = _function_body("emerald_throw_ball")
    assert body.count("em_bag_pocket()") >= 3, (
        "emerald_throw_ball reads em_bag_pocket() fewer than 3 times -- looks like it stopped "
        "reading the live pocket value somewhere in the steering loop"
    )
    assert "local before = em_bag_pocket()" in body
    assert "em_bag_pocket() ~= before" in body, (
        "the pocket-switch wait does not re-read em_bag_pocket() against its own prior value"
    )
    assert "if em_bag_pocket() ~= BALLS_POCKET then" in body, (
        "the final pocket check does not re-read the live value"
    )


def test_emerald_throw_ball_asserts_task_func_before_each_a():
    """Hard rule: assert the exact task func before every A (compare against sym|1). Both
    presses this helper ever sends A on are gated by a task_active(...) check immediately
    before, or (for the pocket-select A) an em_bag_input_ready(cp) check whose own body calls
    task_active(TASK_BAG_MENU_HANDLE_INPUT)."""
    body = _function_body("emerald_throw_ball")
    a_taps = [m.start() for m in re.finditer(r'G\.tap\("A"', body)]
    assert len(a_taps) == 2, f"expected exactly 2 A presses in emerald_throw_ball, found {len(a_taps)}"
    for pos in a_taps:
        before = body[:pos]
        assert "task_active(" in before, (
            "an A press in emerald_throw_ball has no task_active(...) check anywhere before it"
        )


def test_emerald_throw_ball_pairs_bag_gone_with_no_bag_task():
    """Hard rule: pair "bag gone" with "no bag task" on the throw-committed check."""
    body = _function_body("emerald_throw_ball")
    m = re.search(r'local committed = false(?P<tail>.*?)if not committed then', body, re.S)
    assert m, "no throw-committed check block found"
    tail = m.group("tail")
    assert "BATTLE_MAIN_CB2" in tail, "throw-committed check does not test callback2 (bag gone)"
    assert "not task_active(TASK_BAG_MENU_HANDLE_INPUT)" in tail, (
        "throw-committed check does not test for no bag input task"
    )
    assert "not task_active(TASK_ITEM_CONTEXT_SINGLE_ROW)" in tail, (
        "throw-committed check does not test for no bag context-menu task"
    )


def test_emerald_route102_catch_loop_calls_the_throw_helper():
    body = _function_body("emerald_route102_catch_loop")
    assert "emerald_throw_ball(cp," in body


def test_every_new_title_syms_entry_resolves_for_emerald():
    """Card E2-CATCH-LEG's own new symbols -- already covered generically by
    test_gen3_title_syms.py's test_every_entry_matches_its_symbol, re-asserted here by name so
    this card's own falsifier does not depend on that other file staying in sync."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute(f'return dofile("{_SYMS_SCRIPT.replace(chr(92), "/")}")')
    out = mod.for_title("emerald")
    got = {k: out[k] for k in out}
    for name in (
        "BAG_POSITION_ADDR", "BAG_MENU_PTR_ADDR", "TASK_ITEM_CONTEXT_SINGLE_ROW",
        "BATTLE_MAIN_CB2", "LAST_USED_ITEM_ADDR",
    ):
        assert name in got, f"{name}: missing from for_title('emerald')"
        assert isinstance(got[name], int) and got[name] > 0


# -- 6. card E2-LEGS: the four PC legs and faint/whiteout are real, and their group guards bite ---

_E2_LEGS = (
    "emerald_pc_deposit", "emerald_pc_withdraw", "emerald_pc_box_place", "emerald_pc_release",
    "emerald_route102_faint", "emerald_route102_whiteout",
)


def _leg(legs, name):
    for i in range(1, len(legs) + 1):
        if legs[i]["name"] == name:
            return legs[i]
    raise AssertionError(f"leg {name!r} not found")


@pytest.mark.parametrize("name", _E2_LEGS)
def test_e2_legs_are_real_legs_with_kinds_and_sources(legs, name):
    leg = _leg(legs, name)
    assert not leg["open"], f"{name}: still OPEN ({leg['open_reason']})"
    assert leg["run"] is not None, f"{name}: no run()"
    assert _py_list(leg["exercises"]), f"{name}: no exercises"
    assert _py_list(leg["source"]), f"{name}: no pret source"


# A fake GBA RAM so a leg's check(cp) runs under lupa: the same SaveBlock1-pointer chain G.map /
# G.pos read, plus gPlayerPartyCount and slot 0's HP words.
_FAKE_RAM = """
RAM = {}
local function b(a) return RAM[a] or 0 end
memory = {
  read_u8 = b,
  read_u16_le = function(a) return b(a) | (b(a + 1) << 8) end,
  read_s16_le = function(a) local v = b(a) | (b(a + 1) << 8); if v >= 0x8000 then v = v - 0x10000 end; return v end,
  read_u32_le = function(a) return b(a) | (b(a + 1) << 8) | (b(a + 2) << 16) | (b(a + 3) << 24) end,
}
function poke(a, v, n) for i = 0, n - 1 do RAM[a + i] = (v >> (8 * i)) & 0xFF end end
"""
_SB1_PTR, _SB1 = 0x03005D8C, 0x02025A00
_PARTY_COUNT, _PARTY = 0x020244E9, 0x020244EC


def _world(lua, group, num, x, y, party_n, hp, maxhp):
    lua.execute(_FAKE_RAM)
    poke = lua.globals().poke
    poke(_SB1_PTR, _SB1, 4)
    poke(_SB1 + 0, x, 2)
    poke(_SB1 + 2, y, 2)
    poke(_SB1 + 4, group, 1)
    poke(_SB1 + 5, num, 1)
    poke(_PARTY_COUNT, party_n, 1)
    poke(_PARTY + 0x56, hp, 2)
    poke(_PARTY + 0x58, maxhp, 2)
    return lua.eval(f"{{pointers = {{gSaveBlock1Ptr = {{address = {_SB1_PTR}}}}}}}")


def test_pc_group_guard_takes_emerald_pc_sav_and_rejects_the_one_mudkip_town_fixture(lua, legs):
    check = _leg(legs, "emerald_enter_pc")["check"]
    assert check(_world(lua, 0, 10, 6, 17, 2, 20, 20)) is None      # emerald_pc.sav
    why = check(_world(lua, 0, 10, 6, 17, 1, 20, 20))                 # emerald_town.sav
    assert why and "party" in why


def test_faint_group_guard_takes_lowhp_and_rejects_the_full_hp_battle_fixture(lua, legs):
    check = _leg(legs, "emerald_route102_faint")["check"]
    assert check is not None, "emerald_route102_faint starts the lowhp group and needs a check"
    assert check(_world(lua, 0, 17, 21, 16, 1, 1, 20)) is None       # emerald_lowhp.sav
    why = check(_world(lua, 0, 17, 21, 16, 1, 20, 20))                # emerald_battle.sav
    assert why and "HP" in why
    assert check(_world(lua, 0, 17, 22, 16, 1, 1, 20))                # wrong tile still refused


def test_grass_legs_walk_back_to_the_group_origin_before_the_next_legs_check():
    chunks = {}
    for c in _leg_chunks(_SCRIPT_SRC):
        m = _LEG_NAME.search(c)
        if m:
            chunks[m.group("name")] = c
    for name in ("emerald_route102_wild_battle", "emerald_route102_catch"):
        assert "emerald_return_to_grass_origin(cp," in chunks[name], name


# -- 7. SLINK_GEN3_PLAY_STOP_AFTER on EMERALD_LEGS, and the boot's field-free polarity ------------

def test_emerald_stop_after_truncates_and_appends_nothing(module, legs):
    cut = module.emerald_stopped_legs
    got = cut("emerald_save_town")
    names = [got[i]["name"] for i in range(1, len(got) + 1)]
    assert names[-1] == "emerald_save_town"
    assert names == [legs[i]["name"] for i in range(1, len(names) + 1)]
    last = cut(legs[len(legs)]["name"])
    assert len(last) == len(legs)


def test_emerald_stop_after_refuses_an_unknown_leg(module):
    got, why = module.emerald_stopped_legs("no_such_leg")
    assert got is None and "no_such_leg" in why


def test_emerald_boot_counts_frames_only_while_the_field_is_free():
    """pred_ok(cp, "field_controls_locked") is TRUE when sLockFieldControls == 0 (free). The live
    run's boot negated it and waited 9000 frames for a locked field (coordinator, 2026-09-26)."""
    start = _SCRIPT_SRC.index("-- A-only boot (no Start pulse)")
    boot = _SCRIPT_SRC[start:_SCRIPT_SRC.index("shadow = {", start)]
    assert 'G.pred_ok(cp, "callback2") and G.pred_ok(cp, "field_controls_locked")' in boot
    assert 'not G.pred_ok(cp, "field_controls_locked")' not in boot
    save = _function_body("emerald_save_via_menu")
    assert 'not G.pred_ok(cp, "field_controls_locked")' not in save
