"""gen3_scripted_play.lua's LEGS table (card gen3-P3-C3-5).

Pure-Lua checks through lupa: no emulator, no ROM. The script's top-level code only builds the
LEGS table (closures aren't called), so it loads with SLINK_ROOT set and nothing else stubbed —
same shape as test_gen1_scripted_host.py's `dofile` pattern. This does NOT run any leg; it
checks the table's SHAPE (site-kind coverage, citation format, no frame-count terminal), which
is exactly what a runtime BizHawk gate cannot check for itself before it burns emulator minutes.
"""
from __future__ import annotations

import os
import re

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_scripted_play.lua")
with open(_SCRIPT, encoding="utf-8") as _f:
    _SCRIPT_SRC = _f.read()

# docs/gen3_engine_sites.md "PINNED / UNVERIFIED matrix" — the 23 recognized site kinds.
_KNOWN_KINDS = {
    "frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
    "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_done", "save",
    "poison_faint", "borrowed_party", "nature_change", "pc_deposit", "pc_withdraw",
    "pc_box_place", "pc_release_begin", "pc_release", "trade_evolve_species_store",
    "trade_begin", "poison_hp_before",
}

# The card's required minimum coverage (a kind counts whether its leg is open or not — an open
# leg's citation stands in for the run not yet scripted).
_REQUIRED_MIN_COVERAGE = {
    "battle_begin", "battle_end", "faint", "capture_wild", "mon_given", "pc_move", "save",
    "map_load",
}
_EVOLVE_OR_TRADE = {"evolve_species_store", "trade_done"}

# A citation must point under one of these — same test as "is this an actual pret path". `lua/`
# and `include/` cover the handful of legs that cite this repo's own pinned RAM addresses
# (lua/games/gen3_frlge.lua) or pret's constants headers, alongside the map/source data.
_CITATION_ROOTS = ("data/maps", "data/layouts", "src/", "data/", "lua/", "include/")

# Coordinate/map/counter/predicate terminal helpers gen3_scripted_play.lua actually uses.
_TERMINAL_HELPERS = (
    "G.pos", "G.map", "mapid(", "G.pred_ok", "G.pred(", "G.save_counter", "party_count(",
    "wait_for_map_change", "G.mash", "G.flash_domain",
)


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    return runtime


@pytest.fixture(scope="module")
def legs(lua):
    os.environ.setdefault("SLINK_ROOT", _REPO.replace("\\", "/"))
    module = lua.execute(f'return dofile("{_SCRIPT.replace(chr(92), "/")}")')
    return module.LEGS


def _py_list(lua_table):
    """A lupa table (1-based) as a Python list, however it was built."""
    return [lua_table[i] for i in range(1, len(lua_table) + 1)]


def test_the_script_loads_without_running_any_leg(legs):
    """dofile must not touch memory/emu/joypad at module scope — those are only reachable from
    inside a leg's run() closure, which this test never calls."""
    assert len(legs) >= 9


def test_every_leg_names_at_least_one_known_site_kind(legs):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        name = leg["name"]
        kinds = _py_list(leg["exercises"])
        assert kinds, f"leg {name!r} names no site kinds"
        unknown = [k for k in kinds if k not in _KNOWN_KINDS]
        assert not unknown, f"leg {name!r} names unknown kind(s) {unknown}"


def test_every_leg_carries_a_pret_citation(legs):
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        name = leg["name"]
        sources = _py_list(leg["source"])
        assert sources, f"leg {name!r} has no source citations"
        for cite in sources:
            assert any(root in cite for root in _CITATION_ROOTS), (
                f"leg {name!r} citation {cite!r} does not point under data/maps, "
                f"data/layouts, src/ or data/"
            )


def test_required_site_kinds_are_covered_somewhere_in_the_union(legs):
    covered = set()
    for i in range(1, len(legs) + 1):
        covered |= set(_py_list(legs[i]["exercises"]))
    missing = _REQUIRED_MIN_COVERAGE - covered
    assert not missing, f"no leg (open or not) exercises {missing}"
    assert covered & _EVOLVE_OR_TRADE, "no leg exercises evolve_species_store or trade_done"


def test_open_legs_are_marked_and_give_a_reason(legs):
    saw_open = False
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["open"]:
            saw_open = True
            assert leg["open_reason"], f"leg {leg['name']!r} is open with no reason"
    assert saw_open, "expected at least one open leg (catch/PC/faint/gift/trade/evolution)"


def test_pinned_legs_are_not_open(legs):
    pinned = {
        "starter", "rival_battle", "leave_lab_for_parcel", "parcel_fetch", "parcel_deliver",
        "route1_catch", "route1_faint", "viridian_pc_deposit_withdraw", "save",
    }
    seen = set()
    for i in range(1, len(legs) + 1):
        leg = legs[i]
        if leg["name"] in pinned:
            seen.add(leg["name"])
            assert not leg["open"], f"leg {leg['name']!r} should be pinned (run), not open"
    assert seen == pinned


def test_leg_names_are_unique(legs):
    names = [legs[i]["name"] for i in range(1, len(legs) + 1)]
    assert len(names) == len(set(names))


# ── source-level check: no run body ends on a bare frame count ─────────────────────────────────
# A runtime frame BUDGET (G.advance()'s runaway cap, or a bounded `for _ = 1, N do ... end` that
# polls a coordinate/predicate every iteration) is fine and used throughout; what's disallowed is
# a leg whose *only* stop condition is "N frames elapsed" with no coordinate/map/counter/
# predicate check inside the loop. Every `run = function` body in the source is required to
# reference at least one of the terminal helpers (open legs, which only log and return, are
# exempt — they have no loop to terminate).

_RUN_BODY_RE = re.compile(r"run = function\(cp\)(.*?)\n\}", re.DOTALL)


def test_no_run_body_terminates_on_a_bare_frame_count():
    bodies = _RUN_BODY_RE.findall(_SCRIPT_SRC)
    assert len(bodies) >= 9, "expected one run body per leg"
    for body in bodies:
        is_open_stub = "G.phase(" in body and "OPEN" in body and "for " not in body
        if is_open_stub:
            continue
        assert any(h in body for h in _TERMINAL_HELPERS), (
            "a non-open leg's run body has no coordinate/map/counter/predicate terminal helper:\n"
            + body
        )
