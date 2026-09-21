"""gen3_rr_scripted_play.lua's LEGS table (card gen3-P3-C3-7).

Pure-Lua checks through lupa: no emulator, no ROM. The script's top level only builds LEGS
(every leg's closure stays uncalled), so it loads with SLINK_ROOT set and the BizHawk globals
stubbed as CALLABLE TABLES -- `type(gui.x)` is "userdata" in EmuHawk, so a plain function stub
would be the wrong shape and a plain table would not be callable
(reference_bizhawk_api_userdata). This checks the table's SHAPE -- per-leg site kinds,
citations, declared savestate, no frame-count terminal -- which is exactly what a BizHawk gate
cannot check before it burns emulator minutes.
"""
from __future__ import annotations

import os
import re

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_rr_scripted_play.lua")
with open(_SCRIPT, encoding="utf-8") as _f:
    _SCRIPT_SRC = _f.read()

# docs/gen3_engine_sites.md "PINNED / UNVERIFIED matrix" -- the 23 recognized site kinds.
_KNOWN_KINDS = {
    "frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
    "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_done", "save",
    "poison_faint", "borrowed_party", "nature_change", "pc_deposit", "pc_withdraw",
    "pc_box_place", "pc_release_begin", "pc_release", "trade_evolve_species_store",
    "trade_begin", "poison_hp_before",
}

# The card's required coverage for RR. A kind counts whether its leg is open or not: an open
# leg's citation stands in for the run not yet scripted.
_REQUIRED_COVERAGE = {
    "battle_end", "faint", "capture_wild", "pc_move", "pc_deposit", "pc_withdraw", "save",
    "map_load",
}

# There is NO pret source for RR's maps, so citations point at this repo's own receipts,
# pinned-address tables and profiles rather than at data/maps.
_CITATION_ROOTS = ("docs/", "data/games/", "lua/", "src/", "patch/", "include/")

# The savestates tools/mkstates.py produces (lua/tests/mkstate.lua kinds town|battle).
_KNOWN_STATES = {
    "slink_prebattle.State", "slink_battle.State", "slink_actionmenu.State",
    "slink_movemenu.State", "slink_overworld.State", "slink_door.State",
    "slink_pokecenter.State",
}

# RAM/coordinate/counter/predicate terminal helpers this driver actually uses.
_TERMINAL_HELPERS = (
    "G.pos", "G.map", "mapid(", "G.pred_ok", "G.pred(", "in_battle(", "on_field(",
    "party_count(", "player_bmon_hp(", "at_action_menu(", "battle_outcome(",
    "hold_until_map_change(", "walk_to(", "G.save_via_menu", "G.flash_domain",
)

_BIZHAWK_GLOBALS = (
    "memory", "joypad", "emu", "client", "event", "savestate", "gui", "console",
    "movie", "bizstring",
)


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    # Callable tables, not functions: EmuHawk exposes these as userdata, and a stub that is
    # merely a table blows up the moment module-scope code calls one.
    runtime.execute(
        "\n".join(
            f"{name} = setmetatable({{}}, {{ __index = function(t, k)"
            f" local v = setmetatable({{}}, getmetatable(t)); rawset(t, k, v); return v end,"
            f" __call = function() return nil end }})"
            for name in _BIZHAWK_GLOBALS
        )
    )
    return runtime


@pytest.fixture(scope="module")
def module(lua):
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    return lua.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')


@pytest.fixture(scope="module")
def legs(module):
    return module.LEGS


def _py_list(lua_table):
    return [lua_table[i] for i in range(1, len(lua_table) + 1)]


def _each(legs):
    for i in range(1, len(legs) + 1):
        yield legs[i]


def test_the_script_loads_without_running_any_leg(legs):
    """dofile must not touch memory/emu/joypad at module scope; the stubs above would let it,
    so the real guard is that LEGS is built and nothing was executed."""
    assert len(legs) >= 7


def test_every_leg_names_at_least_one_known_site_kind(legs):
    for leg in _each(legs):
        kinds = _py_list(leg["exercises"])
        assert kinds, f"leg {leg['name']!r} names no site kinds"
        unknown = [k for k in kinds if k not in _KNOWN_KINDS]
        assert not unknown, f"leg {leg['name']!r} names unknown kind(s) {unknown}"


def test_every_leg_carries_a_citation(legs):
    for leg in _each(legs):
        sources = _py_list(leg["source"])
        assert sources, f"leg {leg['name']!r} has no source citations"
        for cite in sources:
            assert any(root in cite for root in _CITATION_ROOTS), (
                f"leg {leg['name']!r} citation {cite!r} points at none of {_CITATION_ROOTS}"
            )


def test_required_site_kinds_are_covered_somewhere_in_the_union(legs):
    covered = set()
    for leg in _each(legs):
        covered |= set(_py_list(leg["exercises"]))
    missing = _REQUIRED_COVERAGE - covered
    assert not missing, f"no leg (open or not) exercises {missing}"


def test_every_leg_declares_the_savestate_it_starts_from(legs):
    """RR has no pret map data, so a leg is startable only from a savestate; SLINK_GEN3_PLAY_FROM
    is useless unless each leg says which one."""
    for leg in _each(legs):
        state = leg["state"]
        assert state, f"leg {leg['name']!r} declares no savestate"
        assert state in _KNOWN_STATES, (
            f"leg {leg['name']!r} wants {state!r}, which tools/mkstates.py does not produce"
        )


def test_open_legs_are_marked_and_give_a_reason(legs):
    saw_open = False
    for leg in _each(legs):
        if leg["open"]:
            saw_open = True
            assert leg["open_reason"], f"leg {leg['name']!r} is open with no reason"
            assert leg["run"] is None, (
                f"open leg {leg['name']!r} carries a run body the loop never calls"
            )
    assert saw_open, "expected wild_catch/pc_move_full_party to be open (unpinned RR bag)"


def test_the_runnable_legs_are_the_ones_the_card_asked_for(legs):
    runnable = {leg["name"] for leg in _each(legs) if not leg["open"]}
    assert runnable == {"battle_to_field", "wild_faint", "door_warp", "pc_ops", "save"}
    for leg in _each(legs):
        if not leg["open"]:
            assert leg["run"] is not None, f"leg {leg['name']!r} has no run body"


def test_leg_names_are_unique(legs):
    names = [leg["name"] for leg in _each(legs)]
    assert len(names) == len(set(names))


def test_state_path_resolves_bare_names_and_passes_absolute_ones_through(module):
    fn = module.state_path
    assert fn("slink_door.State").endswith("/slink_door.State")
    assert fn("slink_door.State") != "slink_door.State"          # a dir was prepended
    assert fn("E:/x/slink_door.State") == "E:/x/slink_door.State"
    assert fn("") is None
    assert fn(None) is None


# -- source-level check: no run body ends on a bare frame count -------------------------------
# A frame BUDGET (a bounded `for` that polls a RAM observable every iteration) is fine and used
# throughout; what is disallowed is a leg whose ONLY stop condition is "N frames elapsed".

_RUN_BODY_RE = re.compile(r"run = function\(cp\)(.*?)\n    end,", re.DOTALL)


def test_no_run_body_terminates_on_a_bare_frame_count():
    bodies = _RUN_BODY_RE.findall(_SCRIPT_SRC)
    assert len(bodies) == 5, f"expected one run body per runnable leg, found {len(bodies)}"
    for body in bodies:
        assert any(h in body for h in _TERMINAL_HELPERS), (
            "a leg's run body has no RAM/coordinate/counter/predicate terminal helper:\n" + body
        )


def test_the_driver_never_mashes_start_in_the_overworld():
    """G.mash pulses Start every 16 frames, which opens the START menu the moment a leg lands
    back on the field -- the reason this driver carries its own A-only mash."""
    assert "G.mash(" not in _SCRIPT_SRC


def test_the_shadow_observer_writes_the_rr_result_file():
    assert "gen3_rr_scripted_play_result.txt" in _SCRIPT_SRC
    assert "lua/gen3/shadow_run.lua" in _SCRIPT_SRC
