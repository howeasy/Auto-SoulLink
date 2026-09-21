"""playlib.lua driven over a FAKE GAME (card gen3-P3-C3-9).

playlib takes its game facts by injection, which is exactly what makes it testable without an
emulator: the fake below is a tiny world (a position, a map id, named predicates, a frame clock
and a button model) handed in as the `H` helper table. Every behaviour the three Gen 3 drivers
used to own a private copy of is exercised here once.

`H.finish` raises, so "RESULT: FAIL ..." is an observable outcome rather than a line that
scrolls past while the run keeps going.
"""
from __future__ import annotations

import os

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LUA_REPO = _REPO.replace("\\", "/")
_PLAYLIB = f"{_LUA_REPO}/lua/tests/playlib.lua"
with open(os.path.join(_REPO, "lua", "tests", "playlib.lua"), encoding="utf-8") as _f:
    _PLAYLIB_SRC = _f.read()

# Comments are prose and may NAME the Gen 3 helper module; the CODE must never reach for it.
_CODE = "\n".join(ln for ln in _PLAYLIB_SRC.splitlines() if not ln.lstrip().startswith("--"))

# A fake game: one walkable plane, one map id, named predicates that default to "quiet", and a
# button model where holding a direction for 12 frames moves one tile (the cadence playlib's
# step uses). `W.on_move` / `W.on_a` / `W.on_frame` are the hooks each test uses to make the
# world do something interesting.
_FAKE = r"""
W = { x = 0, y = 0, map = 100, frame = 0, a = 0, log = {}, seen_buttons = {},
      preds = {}, blocked = false, in_battle = false, dir = nil, held = 0 }

local DXY = { Up = {0,-1}, Down = {0,1}, Left = {-1,0}, Right = {1,0} }

function W.reset()
    W.x, W.y, W.map, W.frame, W.a = 0, 0, 100, 0, 0
    W.log, W.seen_buttons, W.preds = {}, {}, {}
    W.blocked, W.in_battle, W.dir, W.held, W.a_down = false, false, nil, 0, false
    W.on_move, W.on_a, W.on_frame = nil, nil, nil
    W.states = {}
    -- every ad-hoc per-test flag, or a leftover leaks into the next test through the
    -- module-scoped runtime (it already hid one real failure)
    W.fought, W.state_fails, W.why, W.ram, W.poll, W.opened = nil, nil, nil, nil, nil, nil
end
function W.tail() return table.concat(W.log, "\n") end

joypad = {
    set = function(t)
        t = t or {}
        W.seen_buttons[#W.seen_buttons + 1] = t
        local dir
        for _, d in ipairs({ "Up", "Down", "Left", "Right" }) do if t[d] then dir = d end end
        if dir then
            if W.dir == dir then W.held = W.held + 1 else W.dir, W.held = dir, 1 end
            if W.held == 12 and not W.blocked then
                W.x, W.y = W.x + DXY[dir][1], W.y + DXY[dir][2]
                if W.on_move then W.on_move() end
            end
        else
            W.dir, W.held = nil, 0
        end
        if t.A and not W.a_down then
            W.a = W.a + 1
            if W.on_a then W.on_a() end
        end
        W.a_down = t.A and true or false
    end,
    get = function() return {} end,
}

memory = {
    read_u8 = function(a) return (W.ram or {})[a] or 0 end,
    read_u16_le = function(a) return (W.ram or {})[a] or 0 end,
    read_u32_le = function(a) return (W.ram or {})[a] or 0 end,
    read_s16_le = function(a) return (W.ram or {})[a] or 0 end,
}
client = { speedmode = function() end, screenshot = function() end, exit = function() end }
savestate = {
    load = function(path)
        W.states[#W.states + 1] = path
        if W.state_fails then return error("no such state", 0) end
        return true
    end,
    save = function() return true end,
}
event = { onframeend = function(fn) W.poll = fn end }
console = { log = function() end }

--- The injected helper table. playlib calls ONLY these names, never a Gen 3 symbol.
H = {
    pos = function() return W.x, W.y end,
    map = function() return W.map // 256, W.map % 256 end,
    -- A predicate is "quiet" (ok) unless a test says otherwise. in_battle has the real
    -- polarity: pred_ok TRUE means NOT in a battle.
    pred_ok = function(_, name)
        if name == "in_battle" then return not W.in_battle end
        if W.preds[name] == nil then return true end
        return W.preds[name]
    end,
    advance = function()
        W.frame = W.frame + 1
        if W.on_frame then W.on_frame(W.frame) end
    end,
    idle = function(n) joypad.set({}); for _ = 1, n do H.advance() end end,
    tap = function(b, hold, gap)
        for _ = 1, (hold or 3) do joypad.set({ [b] = true }); H.advance() end
        H.idle(gap or 13)
    end,
    phase = function(n, d) W.log[#W.log + 1] = "phase " .. n .. " " .. tostring(d) end,
    finish = function(ok, msg)
        W.log[#W.log + 1] = "RESULT: " .. (ok and "PASS" or "FAIL") .. " " .. tostring(msg)
        error("FINISH", 0)
    end,
    shot = function() end,
    open = function(n) W.opened = n end,
    checkpoint = function() return { predicates = {} }, "fakegame" end,
}

function W.guard(fn, ...)
    local args = table.pack(...)
    local ok, err = pcall(function() return fn(table.unpack(args, 1, args.n)) end)
    return ok, W.tail(), tostring(err)
end
"""


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_FAKE)
    return runtime


@pytest.fixture
def world(lua):
    w = lua.globals().W
    w.reset()
    for key in ("SLINK_GEN3_PLAY_FROM", "SLINK_STATE", "SLINK_SHADOW", "SLINK_STATE_DIR"):
        os.environ.pop(key, None)
    return w


def _bind(lua, paths_lua="nil", extra=""):
    return lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f"return PL.bind(H, {{ paths = {paths_lua}, obj_events = 0x02036E38,"
        f" party_count_addr = 0x02024029, state_dir = \"D:/states\"{extra} }})"
    )


def _legs(lua, body):
    return lua.execute(body)


# ── formatting: the multi-return trap ────────────────────────────────────────────────────────


def test_position_formatting_helpers_return_exactly_one_value(lua, world):
    """H.pos returns TWO values, so using it mid-format silently drops every later argument
    (PHYSICAL: three lane runs lost to this). `at`/`where`/`obj_at` return ONE string, which is
    what makes them safe anywhere in an argument list."""
    play = _bind(lua)
    world.x, world.y, world.map = 3, 4, 1284
    assert play.at(None) == "(3,4)"
    assert play.where(None) == "map=1284 at=(3,4)"
    # the real test: still correct when it is NOT the last argument
    assert lua.eval('function(p) return string.format("%s then %s", p.at(nil), "more") end')(
        play
    ) == "(3,4) then more"


def test_readable_mapid_distinguishes_unreadable_from_changed(lua, world):
    play = _bind(lua)
    world.map = 1284
    assert play.mapid(None) == 1284
    assert play.readable_mapid(None) == 1284
    world.map = -257          # H.map returning -1,-1
    assert play.readable_mapid(None) is None
    assert play.mapid(None) == -257


def test_in_battle_polarity(lua, world):
    play = _bind(lua)
    world.in_battle = False
    assert play.in_battle(None) is False
    world.in_battle = True
    assert play.in_battle(None) is True


# ── mash_a ───────────────────────────────────────────────────────────────────────────────────


def test_mash_a_never_presses_start(lua, world):
    """G.mash pulses Start every 16 frames; on the field that opens the START menu. The whole
    reason this helper exists is that it cannot."""
    play = _bind(lua)
    play.mash_a(40, None)
    pressed = lua.eval(
        "function() local n = 0 for _, t in ipairs(W.seen_buttons) do"
        " if t.Start then n = n + 1 end end return n end"
    )()
    assert pressed == 0
    assert "Start" not in _CODE.split("function P.mash_a")[1].split("end")[0]


def test_mash_a_stops_as_soon_as_the_stop_condition_holds(lua, world):
    play = _bind(lua)
    stop = lua.eval("function() return W.a >= 3 end")
    assert play.mash_a(100, stop) is True
    assert world.a <= 4


# ── step / follow ────────────────────────────────────────────────────────────────────────────

_PATHS = '{ p = { from = { 0, 0 }, dirs = { "Right", "Right", "Down" } } }'


def test_follow_walks_a_path_and_ends_where_the_path_says(lua, world):
    play = _bind(lua, _PATHS)
    ok, log, err = world.guard(play.follow, None, "p", "test")
    assert ok, f"{err}\n{log}"
    assert (world.x, world.y) == (2, 1)


def test_follow_refuses_a_path_from_the_wrong_start_tile(lua, world):
    """A precomputed path is only valid from ITS start tile; walking it from anywhere else
    marches into collision (the first FR lane run stalled exactly so)."""
    play = _bind(lua, _PATHS)
    world.x, world.y = 5, 5
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "is not the path's from (0,0)" in log


def test_a_stalled_step_is_retried_after_A_presses(lua, world):
    """A step that does not move is a textbox owning the player, not a wall: clear it with A,
    then retry the SAME step."""
    play = _bind(lua, _PATHS)
    world.blocked = True
    # the "textbox" clears after four A presses -- exactly what one stalled attempt sends
    lua.execute("W.on_a = function() if W.a >= 4 then W.blocked = false end end")
    ok, log, err = world.guard(play.follow, None, "p", "test")
    assert ok, f"{err}\n{log}"
    assert (world.x, world.y) == (2, 1)
    assert world.a >= 4, "the stall recovery never pressed A"


def test_a_step_that_never_moves_fails_loudly(lua, world):
    play = _bind(lua, _PATHS)
    world.blocked = True
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "step Right stalled at (0,0)" in log


def test_step_with_want_requires_the_exact_destination_tile(lua, world):
    """The new-game walk uses the strict form: an unexpected displacement means the timed intro
    went somewhere else, and continuing would be worse than stopping."""
    play = _bind(lua)
    lua.execute("W.on_move = function() W.x = W.x + 3 end")      # the world over-shoots
    assert play.step(None, "Right", 100, True) is False
    lua.execute("W.reset()")
    assert play.step(None, "Right", 100, True) is True


# ── mid-walk wild encounters (FR lane run 12) ────────────────────────────────────────────────


def test_a_wild_encounter_mid_step_is_fought_and_the_path_continues(lua, world):
    """FR run 12 died on "step Left stalled at (9,32)" -- a tall-grass tile with collision 0.
    The stall was a wild encounter starting mid-step. The walker must fight it and carry on,
    not mistake it for geometry."""
    play = _bind(lua, _PATHS)
    lua.execute("""
        W.on_move = function()
            if W.x == 1 and W.y == 0 and not W.fought then W.in_battle = true end
        end
        W.on_a = function()
            if W.in_battle and W.a >= 4 then W.in_battle, W.fought = false, true end
        end
    """)
    ok, log, err = world.guard(play.follow, None, "p", "test")
    assert ok, f"{err}\n{log}"
    assert (world.x, world.y) == (2, 1), "the path did not finish after the battle"
    assert "phase encounter #1 during step Right at (1,0)" in log
    assert "phase encounter-done #1" in log


def test_an_encounter_that_displaces_the_player_fails_loudly(lua, world):
    """A battle does not move the player. One that appears to is a whiteout, which teleports to
    a Pokemon Center and makes every remaining direction in the path meaningless."""
    play = _bind(lua, _PATHS)
    lua.execute("""
        W.on_move = function()
            if W.x == 1 and W.y == 0 and not W.fought then W.in_battle = true end
        end
        W.on_a = function()
            if W.in_battle and W.a >= 4 then
                W.in_battle, W.fought = false, true
                W.x, W.y = 40, 40                    -- whiteout to the Pokemon Center
            end
        end
    """)
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "moved the player from (1,0) to (40,40)" in log
    assert "whiteout" in log


def test_the_encounter_budget_is_bounded_per_path(lua, world):
    play = _bind(lua, _PATHS, extra=", max_encounters = 2")
    lua.execute("W.on_move = function() W.in_battle = true end\n"
                "W.on_a = function() if W.in_battle and W.a % 4 == 0 then W.in_battle = false end end")
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "more than 2 wild encounters on one path" in log


def test_a_path_can_opt_out_of_absorbing_battles(lua, world):
    """FR's ball_to_rival_row lands ON the rival trigger: that battle belongs to the leg's own
    oracle, so the walker must not fight it first."""
    play = _bind(lua, '{ p = { from = { 0, 0 }, dirs = { "Right" }, battles = false } }')
    lua.execute("W.on_move = function() W.in_battle = true end")
    ok, log, err = world.guard(play.follow, None, "p", "test")
    assert ok, f"{err}\n{log}"
    assert "encounter" not in log
    assert world.in_battle is True, "the walker fought a battle the path opted out of"


# ── warps ────────────────────────────────────────────────────────────────────────────────────


def test_enter_warp_presses_into_the_door_until_the_map_changes(lua, world):
    play = _bind(lua)
    lua.execute("W.on_frame = function(f) if f >= 40 then W.map = 1284 end end")
    assert play.enter_warp(None, "Up", 20) is True
    assert world.map == 1284


def test_enter_warp_reports_failure_when_the_map_never_changes(lua, world):
    play = _bind(lua)
    assert play.enter_warp(None, "Up", 3) is False


# ── the debounced scene wait ─────────────────────────────────────────────────────────────────


def test_wait_scene_settled_requires_consecutive_quiet_frames(lua, world):
    """PHYSICAL lesson from FR runs 4-7 and 11: script_context_status and field_controls_locked
    can both read "done" for a frame or two mid-scene. A single read is not a settle."""
    play = _bind(lua)
    lua.execute("""
        W.preds.script_context_status = false
        W.on_frame = function(f)
            -- quiet for 10 frames (a mid-scene flicker), busy again, then quiet for good
            if f >= 5 and f < 15 then W.preds.script_context_status = true
            elseif f < 60 then W.preds.script_context_status = false
            else W.preds.script_context_status = true end
        end
    """)
    assert play.wait_scene_settled(None, 6000, None, 30) is True
    assert world.frame >= 90, "returned during the 10-frame flicker instead of waiting"


def test_wait_scene_settled_gives_up_within_its_budget(lua, world):
    play = _bind(lua)
    lua.execute("W.preds.field_controls_locked = false")
    assert play.wait_scene_settled(None, 50, None, 30) is False


def test_wait_scene_settled_honours_an_extra_ground_truth_predicate(lua, world):
    play = _bind(lua)
    also = lua.eval("function() return W.frame >= 100 end")
    assert play.wait_scene_settled(None, 6000, also, 5) is True
    assert world.frame >= 100


# ── state paths ──────────────────────────────────────────────────────────────────────────────


def test_state_path_resolution(lua, world):
    play = _bind(lua)
    assert play.state_path("a.State") == "D:/states/a.State"
    assert play.state_path("X:/other/a.State") == "X:/other/a.State"
    assert play.state_path("") is None
    assert play.state_path(None) is None


# ── the runner ───────────────────────────────────────────────────────────────────────────────

_RUNNER_LEGS = """
RAN = {}
LEGS = {
  { name = "one",  run = function() RAN[#RAN+1] = "one" end },
  { name = "two",  open = true, open_reason = "not scripted yet" },
  { name = "three", state = "s3.State",
    check = function() return W.why end,
    run = function() RAN[#RAN+1] = "three" end },
}
return LEGS
"""


def _run(lua, world, opts="{ name = \"fake\" }"):
    play = _bind(lua)
    legs = lua.execute(_RUNNER_LEGS)
    return world.guard(lua.eval(f"function(p, L) return p.main(L, {opts}) end"), play, legs)


def test_the_runner_runs_legs_in_order_and_reports_open_ones_separately(lua, world):
    ok, log, _err = _run(lua, world)
    assert not ok                       # H.finish always raises; PASS is in the log
    assert "RESULT: PASS reached: one,three | open (skipped): two" in log
    assert lua.eval("table.concat(RAN, ',')") == "one,three"
    assert "phase skip-open two: not scripted yet" in log


def test_an_open_leg_is_never_run(lua, world):
    ok, log, _err = _run(lua, world)
    assert "phase leg-start two" not in log


def test_the_runner_loads_each_legs_own_savestate(lua, world):
    """Never inherited from whatever the previous leg left behind -- that bug cost an RR lane
    run (door_warp walked out of wild_faint's leftovers and failed on the map id)."""
    _run(lua, world)
    assert list(world.states.values()) == ["D:/states/s3.State"]


def test_slink_state_overrides_only_the_first_legs_state(lua, world):
    os.environ["SLINK_GEN3_PLAY_FROM"] = "three"
    os.environ["SLINK_STATE"] = "Z:/override.State"
    try:
        ok, log, _err = _run(lua, world)
    finally:
        os.environ.pop("SLINK_GEN3_PLAY_FROM")
        os.environ.pop("SLINK_STATE")
    assert list(world.states.values()) == ["Z:/override.State"]
    assert "RESULT: PASS reached: three | open (skipped): " in log


def test_resume_skips_every_leg_before_the_named_one(lua, world):
    os.environ["SLINK_GEN3_PLAY_FROM"] = "three"
    try:
        _run(lua, world)
    finally:
        os.environ.pop("SLINK_GEN3_PLAY_FROM")
    assert lua.eval("table.concat(RAN, ',')") == "three"


def test_resume_on_an_unknown_leg_name_fails_instead_of_silently_starting_over(lua, world):
    os.environ["SLINK_GEN3_PLAY_FROM"] = "nosuchleg"
    try:
        ok, log, _err = _run(lua, world)
    finally:
        os.environ.pop("SLINK_GEN3_PLAY_FROM")
    assert "RESULT: FAIL SLINK_GEN3_PLAY_FROM names no leg: nosuchleg" in log


def test_a_failed_precondition_stops_the_run_before_the_leg_body(lua, world):
    lua.execute('W.why = "a battle is in progress"')
    ok, log, _err = _run(lua, world)
    assert "RESULT: FAIL three: precondition failed: a battle is in progress" in log
    assert lua.eval("table.concat(RAN, ',')") == "one"


def test_a_savestate_that_will_not_load_stops_the_run(lua, world):
    lua.execute("W.state_fails = true")
    ok, log, _err = _run(lua, world)
    assert "RESULT: FAIL three: savestate.load failed" in log


def test_the_boot_hook_runs_before_any_leg(lua, world):
    play = _bind(lua)
    legs = lua.execute(_RUNNER_LEGS)
    lua.execute("BOOTED = nil")
    fn = lua.eval(
        'function(p, L) return p.main(L, { name = "fake",'
        ' boot = function() BOOTED = #RAN end }) end'
    )
    world.guard(fn, play, legs)
    assert lua.eval("BOOTED") == 0


def test_the_observer_is_only_started_when_slink_shadow_is_set(lua, world):
    """...and the boot hook runs FIRST: starting the observer before a cold boot would
    attribute the title screen's own map loads to natural play."""
    src = _CODE
    assert src.index("if o.boot then") < src.index('os.getenv("SLINK_SHADOW")')
    assert src.index('os.getenv("SLINK_SHADOW")') < src.index("for i = from_idx, #LEGS do")


def test_shadow_failures_are_fatal(lua, world):
    body = _CODE.split('if o.shadow and os.getenv("SLINK_SHADOW")')[1]
    assert 'H.finish(false, "shadow: dofile of "' in body
    assert 'H.finish(false, "shadow: observer start failed: "' in body
    assert "shadow: poll failed during " in _CODE


def test_playlib_never_reaches_for_a_gen3_symbol():
    """The whole point of the injection seam: a Gen 1/Gen 2 driver must be able to bind its own
    readers without playlib dragging gen3_boot_check in behind it."""
    for forbidden in ("gen3_boot_check", "gSaveBlock1", "0x0202", "0x0203", "G.mash(",
                      "SLINK_GEN3_CHECKPOINT"):
        assert forbidden not in _CODE, f"{forbidden} appears in playlib CODE (comments are fine)"


# -- whiteout: the one displacement that is recoverable (FR lane run 14) ----------------------


_WHITEOUT_LEGS = """
RAN, RECOVERED = {}, 0
LEGS = {
  { name = "walker",
    recover = function() RECOVERED = RECOVERED + 1; W.map = 100; W.x, W.y = 0, 0 end,
    run = function(cp) RAN[#RAN+1] = "run"; PLAY.follow(cp, "p", "walker") end },
}
return LEGS
"""


def _whiteout_world(lua, fake_faints=1):
    """The walker meets a wild battle on its second tile; `fake_faints` of those battles end in
    a whiteout (the player wakes on map 42), the rest are ordinary wins."""
    lua.execute(f"""
        W.faints_left = {fake_faints}
        W.on_move = function()
            if W.x == 1 and W.y == 0 and not W.fighting then
                W.in_battle, W.fighting = true, true
            end
        end
        W.on_a = function()
            if W.in_battle and W.a % 4 == 0 then
                W.in_battle, W.fighting = false, false
                if W.faints_left > 0 then
                    W.faints_left = W.faints_left - 1
                    W.map = 42                 -- the heal map
                    W.x, W.y = 8, 5
                end
            end
        end
    """)


def _run_whiteout(lua, world, max_recoveries=2):
    play = lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'PLAY = PL.bind(H, {{ paths = {_PATHS}, heal_map = 42,'
        f' max_recoveries = {max_recoveries}, state_dir = "D:/states" }})\n'
        f"return PLAY"
    )
    legs = lua.execute(_WHITEOUT_LEGS)
    return world.guard(
        lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)


def test_a_whiteout_restarts_the_leg_instead_of_failing_it(lua, world):
    """PHYSICAL (FR run 14): the starter fainted in the Route 1 grass and the player woke in
    their house. The observer got its first natural faint AND whiteout out of it, so the walk
    was doing its job -- what was missing was a way to carry on afterwards."""
    _whiteout_world(lua, fake_faints=1)
    ok, log, _err = _run_whiteout(lua, world)
    assert "phase whiteout " in log
    assert "phase whiteout-recover walker: attempt 1 of 2" in log
    assert lua.eval("RECOVERED") == 1
    assert lua.eval("#RAN") == 2, "the leg should have been run again after recovery"
    assert "RESULT: PASS reached: walker" in log


def test_a_leg_that_keeps_whiting_out_is_bounded(lua, world):
    _whiteout_world(lua, fake_faints=9)
    ok, log, _err = _run_whiteout(lua, world, max_recoveries=2)
    assert "RESULT: FAIL walker: whited out 3 times (limit 2)" in log


def test_a_displacement_that_is_not_a_whiteout_is_still_fatal(lua, world):
    """Only a displacement that lands on the heal map has a name. Anything else moved the
    player for a reason nothing here can state, so the path is simply gone."""
    _whiteout_world(lua, fake_faints=1)
    lua.execute("W.on_a = function()"
                " if W.in_battle and W.a % 4 == 0 then"
                "   W.in_battle, W.fighting = false, false; W.map = 77; W.x, W.y = 8, 5 end end")
    ok, log, _err = _run_whiteout(lua, world)
    assert "RESULT: FAIL" in log
    assert "not the heal map" in log
    assert "not a whiteout either" in log


def test_a_leg_with_no_recover_says_so_rather_than_looping(lua, world):
    _whiteout_world(lua, fake_faints=1)
    play = lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'PLAY = PL.bind(H, {{ paths = {_PATHS}, heal_map = 42, state_dir = "D:/states" }})\n'
        f"return PLAY"
    )
    legs = lua.execute("""
        LEGS = { { name = "walker", run = function(cp) PLAY.follow(cp, "p", "walker") end } }
        return LEGS
    """)
    ok, log, _err = world.guard(
        lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    assert "declares no recover()" in log


def test_finish_inside_a_leg_is_not_swallowed_by_the_recovery_pcall(lua, world):
    """run_leg pcalls the leg body; everything that is not the whiteout signal -- above all
    H.finish's own abort -- has to come straight back out."""
    play = _bind(lua)
    legs = lua.execute("""
        return { { name = "boom", run = function() H.finish(false, "a real failure") end } }
    """)
    ok, log, _err = world.guard(
        lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    assert not ok
    assert "RESULT: FAIL a real failure" in log
