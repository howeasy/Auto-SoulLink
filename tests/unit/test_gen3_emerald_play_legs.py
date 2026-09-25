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
    r'check = emerald_at\((?P<g>\d+), (?P<n>\d+), (?P<x>\d+), (?P<y>\d+)\)')


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
    """The 4 legs with a real run(): entering the PC, saving, and the two battles."""
    pinned = {
        "emerald_enter_pc", "emerald_save_town", "emerald_route102_wild_battle",
        "emerald_calvin_trainer_battle",
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
