"""lua/tests/em_carrier_walk.lua: the Emerald Center walk that waits for the companion's trade NPC.

Final cut b6cd75c6, frlgc_whiteout_gen3_em_as_a_companion: "step Up stalled at (10,4)". The
companion spawns a wandering trade NPC in Oldale's Center (emerald.h:144-148 -> map (10,4), range
1,1); it stood on (10,3), the one walkable access to the PC, and playlib's recovery (clear_dialogue
= four A taps) talked to it and opened its Trade menu. The helper under test never presses A on a
blocked step: it idles and retries the same direction, backs an already-open menu out with B, and
fails by name after a bounded wait. Driven over a fake world through lupa, no emulator.
"""
from __future__ import annotations

import os
import re

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_MODULE = os.path.join(_REPO, "lua", "tests", "em_carrier_walk.lua")
_DUO = os.path.join(_REPO, "lua", "tests", "duo", "duo_gen3_main.lua")
_EMERALD_H = os.path.join(_REPO, "patch", "src", "trade_targets", "emerald.h")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _code(path: str) -> str:
    """The file with `--` comment lines removed: prose may say 'A', the code must not press it."""
    return "\n".join(ln for ln in _read(path).splitlines() if not ln.lstrip().startswith("--"))


# A fake Center: the player on a column, a carrier NPC that occupies a tile until `clear_at`
# (frames), an optional open menu. Only directions and B exist as inputs, exactly the module's deps.
_WORLD = r"""
local EMW = dofile(MODULE)
W = { x = 10, y = 4, map = 1, frame = 0, presses = {}, menu = false, finished = nil,
      carrier = { 10, 3 }, clear_at = nil, readable = true, away = { 11, 3 } }
local DXY = { Up = {0,-1}, Down = {0,1}, Left = {-1,0}, Right = {1,0} }
local function wander()
    if W.clear_at and W.frame >= W.clear_at then W.carrier = W.away end
end
local deps = {
    pos = function() return W.x, W.y end,
    map = function() return W.map end,
    hold = function(dir, n)
        for i = 1, n do
            W.frame = W.frame + 1; wander()
            W.presses[#W.presses + 1] = dir
            if i == n and not W.menu then
                local tx, ty = W.x + DXY[dir][1], W.y + DXY[dir][2]
                local hit = (W.carrier and W.carrier[1] == tx and W.carrier[2] == ty)
                    or (W.wall and W.wall[1] == tx and W.wall[2] == ty)
                if not hit then W.x, W.y = tx, ty end
            end
        end
    end,
    idle = function(n) W.frame = W.frame + n; wander() end,
    tap_b = function() W.presses[#W.presses + 1] = "B"; W.menu = false; W.frame = W.frame + 16; wander() end,
    quiet = function() return not W.menu end,
    carrier = function()
        if not W.readable or not W.carrier then return nil end
        return W.carrier[1], W.carrier[2]
    end,
    wait_at = function(x, y) return W.x == x and W.y == y end,
    finish = function(ok, msg) W.finished = { ok = ok, msg = msg } end,
}
W.walker = EMW.new(deps)
W.EMW = EMW
function W.rebuild(over)          -- the same fake with some deps replaced
    local d = {}
    for k, v in pairs(deps) do d[k] = v end
    for k, v in pairs(over) do d[k] = v end
    W.walker = EMW.new(d)
end
function W.run(dirs, to)
    return W.walker.walk({ from = { 10, 4 }, to = to or { 10, 2 }, dirs = dirs }, "whiteout a", "em_oldale_center_to_pc")
end
function W.presses_str() return table.concat(W.presses, ",") end
"""


@pytest.fixture()
def lua():
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.globals().MODULE = _MODULE.replace("\\", "/")
    rt.execute(_WORLD)
    return rt


def test_blocked_step_retries_without_a_and_then_succeeds(lua):
    lua.execute("W.clear_at = 150")                      # the NPC wanders off after ~150 frames
    assert lua.eval('W.run({ "Up", "Up" })') is True
    g = lua.globals().W
    assert (g.x, g.y) == (10, 2)
    assert g.finished is None
    presses = str(lua.eval("W.presses_str()")).split(",")
    assert "A" not in presses                              # NEVER A on a blocked step
    # the blocked step was retried (several Up presses of 12 frames) before it landed
    assert presses.count("Up") > 12 * 2


def test_unblocked_walk_is_one_press_per_tile(lua):
    lua.execute("W.carrier = nil")
    assert lua.eval('W.run({ "Up", "Up" })') is True
    assert lua.eval("#W.presses") == 24                   # 2 steps x 12 frames, no retry, no B


def test_block_past_the_budget_fails_by_name_with_the_carrier_tile(lua):
    lua.execute("W.clear_at = nil")                      # it never leaves
    assert lua.eval('W.run({ "Up", "Up" })') is False
    fin = lua.globals().W.finished
    assert fin.ok is False
    assert "em center walk blocked by carrier NPC at (10,3)" in fin.msg
    assert "whiteout a" in fin.msg and "em_oldale_center_to_pc" in fin.msg
    presses = str(lua.eval("W.presses_str()")).split(",")
    assert "A" not in presses
    # bounded: the wait is the module's budget, not unbounded
    assert lua.eval("W.frame") <= lua.eval("W.EMW.BUDGET") + 100


def test_unreadable_carrier_falls_back_to_the_blocked_step_name(lua):
    lua.execute("W.readable = false")
    assert lua.eval('W.run({ "Up", "Up" })') is False
    assert lua.globals().W.finished.msg.endswith("blocked step (10,4)->(10,3)")


def test_block_not_caused_by_the_carrier_is_not_blamed_on_it(lua):
    lua.execute("W.carrier = { 9, 4 }; W.wall = { 10, 3 }")
    assert lua.eval('W.run({ "Up", "Up" })') is False
    msg = lua.globals().W.finished.msg
    assert "blocked step (10,4)->(10,3)" in msg
    assert "carrier NPC at (9,4), not on the target tile" in msg
    assert "em center walk blocked by carrier NPC" not in msg


def test_open_menu_is_backed_out_with_b_never_a(lua):
    lua.execute("W.menu = true; W.carrier = nil")        # the Trade menu is already up
    assert lua.eval('W.run({ "Up", "Up" })') is True
    presses = str(lua.eval("W.presses_str()")).split(",")
    assert presses[0] == "B"                              # first input is the back-out
    assert "A" not in presses
    assert (lua.globals().W.x, lua.globals().W.y) == (10, 2)
    # no direction was pressed while the menu was open (it would move the menu cursor)
    assert presses.index("Up") > presses.index("B")


def test_menu_that_never_closes_fails_without_a(lua):
    lua.execute("W.carrier = nil; W.rebuild({ quiet = function() return false end, "
                "tap_b = function() W.presses[#W.presses + 1] = 'B'; W.frame = W.frame + 16 end })")
    assert lua.eval('W.run({ "Up" })') is False
    presses = str(lua.eval("W.presses_str()")).split(",")
    assert "A" not in presses and set(presses) == {"B"}
    assert "blocked step" in lua.globals().W.finished.msg


def test_map_change_mid_path_counts_as_the_warp(lua):
    lua.execute("W.carrier = nil; W.rebuild({ hold = function(dir, n) W.frame = W.frame + n; W.map = 2 end })")
    assert lua.eval('W.run({ "Down", "Down" }, { 7, 8 })') is True
    assert lua.globals().W.finished is None


# ── the wiring: the old recovery must not be what walks these two paths ────────────────────────

def test_module_never_names_the_a_button():
    code = _code(_MODULE)
    assert not re.search(r"""["']A["']""", code), "em_carrier_walk must not be able to press A"
    assert "clear_dialogue" not in code and "mash" not in code


def test_both_emerald_center_walks_use_the_one_helper_not_play_follow():
    code = _code(_DUO)
    assert 'em_center_walk("em_oldale_center_to_pc", label)' in code
    assert 'em_center_walk("em_pc_to_center_door", label)' in code
    # play.follow's recovery taps A (clear_dialogue); it is what opened the Trade menu
    assert not re.search(r"""play\.follow\(\s*cp\s*,\s*["']em_(oldale_center_to_pc|pc_to_center_door)["']""", code)
    assert not re.search(r"""traced_follow\(\s*cp\s*,\s*["']em_(oldale_center_to_pc|pc_to_center_door)["']""", code)
    # FR/LG/RR walks are untouched: they still go through play.follow / traced_follow
    assert 'play.follow(cp, "pc_to_pokecenter_entrance", label)' in code
    assert 'play.follow(cp, "pokecenter_entrance_to_pc", label)' in code
    assert 'SP.traced_follow(cp, "pokecenter_door_to_route1_edge", label)' in code


def test_carrier_local_id_matches_the_patch():
    m = re.search(r"SLINK_TARGET_CARRIER_LOCAL_ID\s+0x([0-9a-fA-F]+)u", _read(_EMERALD_H))
    assert m, "emerald.h no longer defines SLINK_TARGET_CARRIER_LOCAL_ID"
    mod = re.search(r"CARRIER_LOCAL_ID\s*=\s*0x([0-9A-Fa-f]+)", _read(_MODULE))
    assert mod and int(mod.group(1), 16) == int(m.group(1), 16)


def test_lua_files_compile():
    rt = LuaRuntime()
    check = rt.eval("function(src) local f, e = load(src); return f and '' or tostring(e) end")
    for path in (_MODULE, _DUO):
        assert check(_read(path)) == "", path
