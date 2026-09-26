"""Card driver-robust: ONE ledge-aware step rule (lua/tests/gen2_walk.lua) under every Gen 2 scripted walker.
No emulator: synthetic maps in, the first step out.

A HOP_* tile is LAND one stands on (.CheckWalkable, engine/overworld/player_movement.asm:735-741); from it a
press in its hop direction whose plain step bumps jumps two tiles (.TryStep then .TryJump, :354-377). The
route-facts grid keeps ledges as walls (0) and the live observer's passable set leaves HOP_* out, so the
ledges ride a separate `map.ledges` field."""
from __future__ import annotations

from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
ALL = {"Up": True, "Down": True, "Left": True, "Right": True}
# 1x4 column: (0,0) floor start, (0,1) a HOP_DOWN ledge, (0,2) its wall face, (0,3) floor or grass beyond.
COLUMN = [1, 0, 0, 1]
LEDGE = [{"x": 0, "y": 1, "dirs": ["Down"]}]
# The observer's live permissions standing at (0,0) and on the ledge: HOP_* and the wall face read closed.
AT_TOP = dict(ALL, Down=False)
ON_LEDGE = dict(ALL, Down=False)


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua


def load(lua, rel):
    return lua.eval("dofile")((ROOT / rel).as_posix())


def lua_list(values):
    return {i + 1: v for i, v in enumerate(values)}


def column(lua, grid=COLUMN, ledges=LEDGE):
    m = {"map_group": 1, "map_number": 1, "map_const": "M", "width": 1, "height": 4, "grid": lua_list(grid),
         "warps": {}}
    if ledges is not None:
        m["ledges"] = lua_list([dict(edge, dirs=lua_list(edge["dirs"])) for edge in ledges])
    return lua.table_from(m, recursive=True)


def pt(lua, x, y, can_step):
    return lua.table_from({"x": x, "y": y, "can_step": can_step, "blocked": {}}, recursive=True)


def goal(lua, x, y):
    return lua.table_from({"x": x, "y": y})


# --- the rule itself ---------------------------------------------------------------------------------

def test_the_step_rule_is_try_step_then_try_jump():
    lua = runtime()
    W = load(lua, "lua/tests/gen2_walk.lua")
    down = W.DIRECTIONS[3]
    step = W.stepper(column(lua), lua.table_from(AT_TOP))
    assert step(0, 0, down, True) == (0, 1, 1)          # onto the ledge: land, whatever can_step says
    assert step(0, 1, down, False) == (0, 3, 1)         # the wall face bumps .TryStep: .TryJump lands two on
    assert step(0, 1, W.DIRECTIONS[1], False) == (0, 0, 1)   # Up: no hop direction, a plain step back
    # a walkable tile right below the ledge is a plain one-tile step (.TryStep wins)
    step = W.stepper(column(lua, grid=[1, 0, 1, 1]), lua.table_from(ALL))
    assert step(0, 1, down, True) == (0, 2, 1)
    # without ledge facts the grid is the old conservative one
    step = W.stepper(column(lua, ledges=None), lua.table_from(AT_TOP))
    assert step(0, 0, down, True) is None and step(0, 1, down, False) is None


# --- every walker, red before the shared rule --------------------------------------------------------

def test_scripted_play_route_hops_the_ledge():
    lua = runtime()
    P = load(lua, "lua/tests/gen2_scripted_play.lua")
    assert P.direction(column(lua), pt(lua, 0, 0, AT_TOP), goal(lua, 0, 3)) == "Down"
    assert P.direction(column(lua), pt(lua, 0, 1, ON_LEDGE), goal(lua, 0, 3)) == "Down"
    assert P.direction(column(lua, ledges=None), pt(lua, 0, 0, AT_TOP), goal(lua, 0, 3))[0] is None


def test_write_windows_route_hops_the_ledge():
    lua = runtime()
    U = load(lua, "lua/tests/gen2_write_windows.lua")
    assert U.step_toward(column(lua), pt(lua, 0, 0, AT_TOP), goal(lua, 0, 3)) == "Down"
    assert U.step_toward(column(lua), pt(lua, 0, 1, ON_LEDGE), goal(lua, 0, 3)) == "Down"
    assert U.step_toward(column(lua, ledges=None), pt(lua, 0, 0, AT_TOP), goal(lua, 0, 3))[0] is None


def test_poison_route_hops_the_ledge():
    lua = runtime()
    PI = load(lua, "lua/tests/gen2_poison_inputs.lua")
    goals = lua.table_from({1: goal(lua, 0, 3)})
    assert PI.step_toward(column(lua), pt(lua, 0, 0, AT_TOP), goals) == "Down"
    assert PI.step_toward(column(lua), pt(lua, 0, 1, ON_LEDGE), goals) == "Down"


@pytest.mark.parametrize("rel,fn", [("lua/tests/gen2_frame_align.lua", "walk_direction"),
                                    ("lua/tests/gen2_write_windows.lua", "grass_step")])
def test_grass_oscillation_hops_off_a_ledge_onto_grass(rel, fn):
    lua = runtime()
    walk = load(lua, rel)[fn]
    grass = [1, 0, 0, 2]
    assert walk(column(lua, grid=grass), pt(lua, 0, 1, ON_LEDGE), None) == "Down"
    assert walk(column(lua, grid=grass, ledges=None), pt(lua, 0, 1, ON_LEDGE), None)[0] is None


@pytest.mark.parametrize("rel", ["lua/tests/gen2_scripted_play.lua", "lua/tests/gen2_write_windows.lua",
                                 "lua/tests/gen2_frame_align.lua", "lua/tests/gen2_poison_inputs.lua"])
def test_a_walker_copied_away_from_its_sibling_loads_the_rule_from_slink_root(rel, tmp_path, monkeypatch):
    """EVO-U1 ran a copy of gen2_frame_align.lua from a scratch path: no gen2_walk.lua beside it."""
    copy = tmp_path / Path(rel).name
    copy.write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("SLINK_ROOT", ROOT.as_posix())
    assert load(runtime(), copy) is not None   # ROOT / an absolute path is that path


@pytest.mark.parametrize("rel", ["lua/tests/gen2_frame_align.lua", "lua/tests/gen2_write_windows.lua"])
def test_a_top_level_gate_script_finds_the_rule_through_slink_root(rel, tmp_path, monkeypatch):
    """EmuHawk runs a --lua= script with source "main" (no path) and relative dofile does not resolve from the
    repo (EmuHawk probe 2026-09-24; the 76d715e6 Crystal U1 run idled to its 3600 s timeout, no result file).
    Modelled here: the chunk text has no @path and the process cwd is elsewhere."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLINK_ROOT", ROOT.as_posix())
    lua = runtime()
    assert lua.execute((ROOT / rel).read_text(encoding="utf-8")) is not None
