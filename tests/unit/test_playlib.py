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
    W.states, W.saved, W.objects, W.party = {}, {}, { { 3, 4, 0x02 } }, 1
    W.save_fails, W.map_reads, W.unreadable_after = nil, 0, nil
    W.sliding, W.landed, W.cleared, W.backs = false, nil, nil, 0
    W.map_unreadable, W.on_field = false, true
    W.reject_hook, W.no_observer, W.poll_raises, W.obs_status = nil, nil, nil, nil
    W.polls, W.unregistered, W.poll_fn = 0, nil, nil
    -- every ad-hoc per-test flag, or a leftover leaks into the next test through the
    -- module-scoped runtime (it already hid one real failure)
    W.fought, W.state_fails, W.why, W.opened = nil, nil, nil, nil
end
function W.tail() return table.concat(W.log, "\n") end

function W.guard(fn, ...)
    local args = table.pack(...)
    local ok, err = pcall(function() return fn(table.unpack(args, 1, args.n)) end)
    return ok, W.tail(), tostring(err)
end

--- One frame of held buttons, applied to the world: holding a direction for 12 frames moves a
--- tile (the cadence playlib's step uses), and A presses are counted on their rising edge.
function W.apply(t)
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
end

--- The injected helper table. playlib calls ONLY these, never a host global and never a Gen 3
--- symbol -- which is exactly why this fake can be a plain Lua table with no emulator behind it.
--- The object layout below is DELIBERATELY not the GBA one (stride 3, no +7 coordinate bias,
--- facing in the low nibble): a library that still knew Gen 3's would fail these.
H = {
    pos = function() return W.x, W.y end,
    -- nil is "unreadable", and playlib must never read that as "changed"
    map = function()
        W.map_reads = (W.map_reads or 0) + 1
        if W.unreadable_after and W.map_reads > W.unreadable_after then return nil end
        if W.map_unreadable then return nil end
        return W.map
    end,
    in_battle = function() return W.in_battle end,
    moving = function() return W.sliding and true or false end,
    on_field  = function() return W.on_field ~= false and not W.in_battle end,
    scene_quiet = function()
        if W.preds.scene_quiet == nil then return true end
        return W.preds.scene_quiet
    end,
    advance = function()
        W.frame = W.frame + 1
        if W.on_frame then W.on_frame(W.frame) end
        -- A registered frame-end callback RUNS, every frame, like the emulator's. A fake that
        -- only stores it cannot tell a polled observer from an unpolled one (Codex cx-bc675fa4).
        if W.poll_fn then W.poll_fn() end
    end,
    idle = function(n) H.press({}); for _ = 2, n do H.advance() end end,
    press = function(buttons) W.apply(buttons); H.advance() end,
    tap = function(b, hold, gap)
        for _ = 1, (hold or 3) do H.press({ [b] = true }) end
        H.idle(gap or 13)
    end,
    phase = function(n, d) W.log[#W.log + 1] = "phase " .. n .. " " .. tostring(d) end,
    finish = function(ok, msg)
        W.log[#W.log + 1] = "RESULT: " .. (ok and "PASS" or "FAIL") .. " " .. tostring(msg)
        error("FINISH", 0)
    end,
    shot = function() end,
    open = function(n) W.opened = n end,
    checkpoint = function() return { fake = true }, "fakegame" end,
    set_budget = function(n) W.budget = n end,
    -- A NON-GBA object layout: 3 bytes per object, no coordinate bias, facing in the low nibble.
    obj_pos = function(i)
        local o = W.objects[(i or 0) + 1]
        return o[1], o[2]
    end,
    obj_facing = function(i) return W.objects[(i or 0) + 1][3] & 0x0F end,
    party_count = function() return W.party end,
    load_state = function(path)
        W.states[#W.states + 1] = path
        return not W.state_fails
    end,
    save_state = function(path)
        W.saved[#W.saved + 1] = path
        return not W.save_fails
    end,
    register_frame_end = function(fn, name)
        if W.reject_hook then return nil end
        W.poll_fn, W.hook_name = fn, name
        return "hook-1"
    end,
    unregister_frame_end = function(id) W.unregistered = id; W.poll_fn = nil end,
    observer = function(result)
        W.observer_result = result
        if W.no_observer then return nil, "the observer refused to start" end
        return {
            poll = function()
                W.polls = (W.polls or 0) + 1
                if W.poll_raises then error("poll blew up", 0) end
            end,
            status = function() return W.obs_status or { registered = 3 } end,
            detail = "fake observer",
        }
    end,
}

H_OBSERVER_ORIG = H.observer

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
    """Bind playlib over the fake. The battle POLICY is part of the binding now -- playlib
    refuses to guess how a game fights a battle it did not choose."""
    return lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'PLAY_LAST = PL.bind(H, {{ paths = {paths_lua}, state_dir = "D:/states",\n'
        f'  clear_dialogue = function() for _ = 1, 4 do H.tap("A", 3, 13) end end,\n'
        f'  advance_scene = function() H.tap("A", 2, 10) end,\n'
        f'  menu_back = function(_, gap) W.backs = (W.backs or 0) + 1; H.tap("B", 3, gap or 20) end,\n'
        f'  battle = function(cp, budget)\n'
        f'      return PLAY_LAST.mash_a(budget or 200,\n'
        f'                              function() return not H.in_battle(cp) end)\n'
        f'  end{extra} }})\n'
        f"return PLAY_LAST"
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


def test_an_unreadable_map_is_nil_not_a_sentinel_number(lua, world):
    """The first cut folded "unreadable" into -257, which compares unequal to every real map
    and so read as "the map changed" -- a warp oracle that cannot tell those apart reports
    warps that never happened (Codex cx-67a6e199)."""
    play = _bind(lua)
    world.map = 1284
    assert play.map(None) == 1284
    world.map_unreadable = True
    assert play.map(None) is None


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
    assert "never came to rest on the path's from (0,0)" in log


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
    assert play.step(None, "Right", 100, True)[0] is False
    lua.execute("W.reset()")
    assert play.step(None, "Right", 100, True) is True   # a bare true, no reason


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
    assert "displaced the player" in log
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
    ok, detail = play.enter_warp(None, "Up", 20)
    assert ok, detail
    assert world.map == 1284


def test_enter_warp_reports_failure_when_the_map_never_changes(lua, world):
    play = _bind(lua)
    ok, detail = play.enter_warp(None, "Up", 3)
    assert not ok
    assert "map never changed" in detail


# ── the debounced scene wait ─────────────────────────────────────────────────────────────────


def test_wait_scene_settled_requires_consecutive_quiet_frames(lua, world):
    """PHYSICAL lesson from FR runs 4-7 and 11: script_context_status and field_controls_locked
    can both read "done" for a frame or two mid-scene. A single read is not a settle."""
    play = _bind(lua)
    lua.execute("""
        W.preds.scene_quiet = false
        W.on_frame = function(f)
            -- quiet for 10 frames (a mid-scene flicker), busy again, then quiet for good
            if f >= 5 and f < 15 then W.preds.scene_quiet = true
            elseif f < 60 then W.preds.scene_quiet = false
            else W.preds.scene_quiet = true end
        end
    """)
    assert play.wait_scene_settled(None, 6000, None, 30) is True
    assert world.frame >= 90, "returned during the 10-frame flicker instead of waiting"


def test_wait_scene_settled_gives_up_within_its_budget(lua, world):
    play = _bind(lua)
    lua.execute("W.preds.scene_quiet = false")
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
    assert "RESULT: FAIL three: could not load the savestate" in log


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


def test_shadow_failures_are_fatal():
    assert "shadow: the observer did not start" in _CODE
    assert "shadow: poll failed" in _CODE
    assert "shadow: the observer is unhealthy" in _CODE


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
        f'PLAY = PL.bind(H, {{ paths = {_PATHS}, heal_map = 42,\n'
        f'  clear_dialogue = function() for _ = 1, 4 do H.tap("A", 3, 13) end end,\n'
        f'  advance_scene = function() H.tap("A", 2, 10) end,\n'
        f'  menu_back = function(_, gap) W.backs = (W.backs or 0) + 1; H.tap("B", 3, gap or 20) end,\n'
        f'  max_recoveries = {max_recoveries}, state_dir = "D:/states",\n'
        f'  battle = function(cp, budget)\n'
        f'      return PLAY.mash_a(budget or 200,\n'
        f'                         function() return not H.in_battle(cp) end)\n'
        f'  end }})\n'
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
        f'PLAY = PL.bind(H, {{ paths = {_PATHS}, heal_map = 42, state_dir = "D:/states",\n'
        f'  clear_dialogue = function() for _ = 1, 4 do H.tap("A", 3, 13) end end,\n'
        f'  advance_scene = function() H.tap("A", 2, 10) end,\n'
        f'  menu_back = function(_, gap) W.backs = (W.backs or 0) + 1; H.tap("B", 3, gap or 20) end,\n'
        f'  battle = function(cp, budget)\n'
        f'      return PLAY.mash_a(budget or 200,\n'
        f'                         function() return not H.in_battle(cp) end)\n'
        f'  end }})\n'
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


def test_a_leg_whose_run_raises_is_finished_by_name(lua, world):
    """A Lua error in a leg body used to be re-raised bare: no RESULT, screenshot or phase trail,
    only the gate timeout (Emerald lost a 1500 s run; OMP cx-7ebf0d0f #8)."""
    play = _bind(lua)
    legs = lua.execute("""
        return { { name = "boom", run = function() local t = nil; return t.x end } }
    """)
    ok, log, _err = world.guard(
        lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    assert not ok
    assert "RESULT: FAIL boom: run raised:" in log
    assert log.count("RESULT:") == 1


def test_a_leg_whose_check_raises_is_finished_by_name(lua, world):
    play = _bind(lua)
    legs = lua.execute("""
        return { { name = "guard", check = function() error("probe blew up") end,
                   run = function() RAN_GUARD = true end } }
    """)
    ok, log, _err = world.guard(
        lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    assert not ok
    assert "RESULT: FAIL guard: check raised:" in log and "probe blew up" in log
    assert lua.eval("RAN_GUARD") is None


# == the Codex cx-67a6e199 findings, one test each ============================================


def test_the_object_readers_are_the_bindings_not_the_librarys(lua, world):
    """The fake's object layout is deliberately NOT the GBA one -- three fields per object, no
    +7 coordinate bias, facing in the LOW nibble. A library that still knew gObjectEvents'
    stride, bias and nibble would read rubbish here."""
    play = _bind(lua)
    lua.execute("W.objects = { {11, 22, 0x35}, {3, 4, 0x01} }")
    assert play.obj_pos(0) == (11, 22)
    assert play.obj_at(0) == "(11,22)"
    assert play.obj_facing(0) == 5           # low nibble of 0x35, not the high one
    assert play.obj_pos(1) == (3, 4)
    for banned in ("0x24", "0x10", "0x12", "0x18", "- 7", ">> 4"):
        assert banned not in _CODE, f"{banned} is a Gen 3 object-layout fact inside playlib"


def test_playlib_calls_no_host_global(lua, world):
    """The rejection in one line: a library that reaches for memory/joypad/savestate/event/
    dofile is bound to one emulator, not to a game."""
    for host in ("memory.", "joypad.", "client.", "event.", "savestate.", "dofile(", "emu."):
        assert host not in _CODE, f"{host} is a host call inside playlib"


def test_a_warp_is_refused_while_the_map_is_unreadable(lua, world):
    play = _bind(lua)
    world.map_unreadable = True
    ok, detail = play.enter_warp(None, "Up", 5)
    assert not ok
    assert "unreadable before the warp" in detail


def test_a_follow_is_refused_while_the_map_is_unreadable(lua, world):
    play = _bind(lua, _PATHS)
    world.map_unreadable = True
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "the map id is unreadable before the walk" in log


def test_a_walk_that_ends_on_the_wrong_tile_fails(lua, world):
    """Every step "succeeded" and the map never changed, but the player is not where the path
    says it put them -- so the path was not walked, whatever the step count says."""
    play = _bind(lua, '{ p = { from = { 0, 0 }, dirs = { "Right", "Right" }, to = { 9, 9 } } }')
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "the walk ended at (2,0), not the path's to (9,9)" in log


def test_a_battle_that_only_changes_the_map_is_still_a_displacement(lua, world):
    """(8,5) in a house is not (8,5) on a route. Comparing coordinates alone called this fine."""
    play = _bind(lua, _PATHS)
    lua.execute("""
        W.on_move = function()
            if W.x == 1 and W.y == 0 and not W.fought then W.in_battle = true end
        end
        W.on_a = function()
            if W.in_battle and W.a >= 4 then
                W.in_battle, W.fought = false, true
                W.map = 999                 -- same tile, different map
            end
        end
    """)
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "displaced the player" in log
    assert "map 100 at (1,0) -> map 999" in log


def test_a_direct_step_allocates_one_encounter_budget_for_the_whole_call(lua, world):
    """A fresh {n=0} per encounter makes the bound meaningless: the count never reaches it.
    One budget per step call means a tile that keeps jumping the player eventually says so."""
    play = _bind(lua, extra=", max_encounters = 3")
    lua.execute("""
        W.blocked = true                      -- the step can never succeed
        W.rearm = 0
        -- a tile that jumps the player every single time they try to step off it
        W.on_frame = function(f) if not W.in_battle and f >= W.rearm then W.in_battle = true end end
        W.on_a = function()
            if W.in_battle and W.a % 3 == 0 then
                W.in_battle = false
                W.rearm = W.frame + 20
            end
        end
    """)
    ok, log, _err = world.guard(play.step, None, "Right", 100, None, None)
    assert not ok
    assert "more than 3 wild encounters" in log


def test_an_override_applies_to_the_first_runnable_leg_when_the_resume_target_is_open(lua, world):
    """SLINK_STATE is the operator's, and it should not be silently dropped because the leg
    they resumed at turns out to be an open one, nor because that leg declares no state."""
    play = _bind(lua)
    legs = lua.execute("""
        RAN = {}
        return {
          { name = "skipme", open = true, open_reason = "not scripted" },
          { name = "stateless", run = function() RAN[#RAN+1] = "stateless" end },
          { name = "later", state = "s.State", run = function() RAN[#RAN+1] = "later" end },
        }
    """)
    os.environ["SLINK_GEN3_PLAY_FROM"] = "skipme"
    os.environ["SLINK_STATE"] = "Z:/override.State"
    try:
        ok, log, _err = world.guard(
            lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    finally:
        os.environ.pop("SLINK_GEN3_PLAY_FROM")
        os.environ.pop("SLINK_STATE")
    # the override lands on `stateless` (which declares none) and is spent there
    assert list(world.states.values()) == ["Z:/override.State", "D:/states/s.State"]
    assert "RESULT: PASS reached: stateless,later | open (skipped): skipme" in log


def test_a_frame_end_registration_that_is_refused_fails_the_run(lua, world):
    """An observer nobody polls drains nothing, and a run that observed nothing while
    reporting PASS is worse than a failure."""
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    world.reject_hook = True
    os.environ["SLINK_SHADOW"] = "1"
    try:
        ok, log, _err = world.guard(
            lua.eval('function(p, L) return p.main(L,'
                     ' { name = "fake", shadow = { result = "r.txt" } }) end'), play, legs)
    finally:
        os.environ.pop("SLINK_SHADOW")
    assert "RESULT: FAIL" in log
    assert "the frame-end poll could not be registered" in log


def test_an_observer_that_reports_trouble_fails_the_run(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    os.environ["SLINK_SHADOW"] = "1"
    try:
        for status, expected in (
            ("{ registered = 3, failed = 'a hook blew up' }", "failed=a hook blew up"),
            ("{ registered = 3, dropped = 7 }", "dropped=7"),
            ("{ registered = 3, rejected = 2 }", "rejected=2"),
            ("{ registered = 3, closed = true }", "the signal queue is closed"),
            ("{ registered = 0 }", "registered=0"),
        ):
            world.reset()
            lua.execute(f"W.obs_status = {status}")
            ok, log, _err = world.guard(
                lua.eval('function(p, L) return p.main(L,'
                         ' { name = "fake", shadow = { result = "r.txt" } }) end'), play, legs)
            assert "RESULT: FAIL" in log, status
            assert expected in log, (status, log)
    finally:
        os.environ.pop("SLINK_SHADOW")


def test_a_healthy_observer_is_polled_and_unregistered_at_the_end(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() H.idle(5) end } }')
    os.environ["SLINK_SHADOW"] = "1"
    try:
        ok, log, _err = world.guard(
            lua.eval('function(p, L) return p.main(L,'
                     ' { name = "fake", shadow = { result = "r.txt" } }) end'), play, legs)
    finally:
        os.environ.pop("SLINK_SHADOW")
    assert "RESULT: PASS" in log
    assert world.observer_result == "r.txt"
    assert world.unregistered == "hook-1", "the frame-end hook outlived the run"


def test_the_resume_target_is_validated_before_the_boot(lua, world):
    """A typo should not cost a cold boot first."""
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    lua.execute("BOOTED = nil")
    os.environ["SLINK_GEN3_PLAY_FROM"] = "nope"
    try:
        ok, log, _err = world.guard(
            lua.eval('function(p, L) return p.main(L, { name = "fake",'
                     ' boot = function() BOOTED = true end }) end'), play, legs)
    finally:
        os.environ.pop("SLINK_GEN3_PLAY_FROM")
    assert "names no leg: nope" in log
    assert lua.eval("BOOTED") is None, "the boot ran before the resume target was checked"


# == Codex cx-bc675fa4, round 5 ===============================================================


def test_an_unreadable_tile_is_not_a_step(lua, world):
    """H.pos can report (-1,-1) exactly when the map id is unreadable, so a tile that merely
    went unreadable would otherwise read as a move -- and then as progress along a path."""
    play = _bind(lua)
    lua.execute("""
        W.blocked = true
        W.on_frame = function(f)
            if f > 20 then W.map_unreadable = true; W.x, W.y = -1, -1 end
        end
    """)
    assert play.step(None, "Right", 100, None, False)[0] is False


def test_an_unreadable_map_is_not_a_warp_even_from_an_unknown_start(lua, world):
    play = _bind(lua)
    world.map_unreadable = True
    assert play.step(None, "Right", None, None, False)[0] is False


def test_a_walk_that_ends_unreadable_is_refused(lua, world):
    """The last guard on the path: a walk whose final map cannot be read cannot be said to have
    ended anywhere. It is a defensive one -- a step only reports success on a readable map, so
    the window is narrow -- which is exactly why it is worth pinning rather than trusting. The
    fake goes unreadable after the FIRST map read, i.e. between follow's start check and its
    end check."""
    play = _bind(lua, '{ p = { from = { 0, 0 }, dirs = { }, to = { 0, 0 } } }')
    world.unreadable_after = 1
    ok, log, _err = world.guard(play.follow, None, "p", "test")
    assert not ok
    assert "the map id unreadable" in log


def test_enter_warp_rechecks_the_field_after_its_settle(lua, world):
    """The settle's own 16 frames are exactly when a second fade can take the field back."""
    play = _bind(lua)
    lua.execute("""
        W.on_frame = function(f)
            if f >= 40 then W.map = 1284 end
            -- the field comes up, then a second fade pulls it away for a while
            W.on_field = not (f >= 45 and f < 400)
        end
    """)
    ok, detail = play.enter_warp(None, "Up", 20)
    assert ok, detail
    assert world.frame >= 400, "returned success from a read taken before the settle"


def test_the_dialogue_and_scene_policies_are_the_bindings(lua, world):
    """Which button dismisses a textbox is a per-game fact; a library that assumes A is a
    library that only works on one game."""
    play = lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'return PL.bind(H, {{ paths = {_PATHS} }})'          # no policies at all
    )
    lua.execute("W.blocked = true")
    ok, log, _err = world.guard(play.step, None, "Right", 100, None, False)
    assert not ok
    assert "no opts.clear_dialogue" in log

    world.reset()
    lua.execute("W.preds.scene_quiet = false")
    ok, log, _err = world.guard(play.wait_scene_settled, None, 100, None, 5)
    assert not ok
    assert "no opts.advance_scene" in log


def _shadow_run(lua, world, play, legs, opts='{ name = "fake", shadow = { result = "r.txt" } }'):
    os.environ["SLINK_SHADOW"] = "1"
    try:
        return world.guard(
            lua.eval(f'function(p, L) return p.main(L, {opts}) end'), play, legs)
    finally:
        os.environ.pop("SLINK_SHADOW")


def test_the_observer_is_actually_polled_every_frame(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() H.idle(30) end } }')
    ok, log, _err = _shadow_run(lua, world, play, legs)
    assert "RESULT: PASS" in log
    assert world.polls >= 30, f"the observer was polled {world.polls} times"


def test_a_poll_that_raises_fails_the_run(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() H.idle(10) end } }')
    world.poll_raises = True
    ok, log, _err = _shadow_run(lua, world, play, legs)
    assert "RESULT: FAIL" in log
    assert "poll failed" in log


def test_health_that_deteriorates_DURING_a_leg_fails_the_run(lua, world):
    """Installing the bad status before startup would let the post-leg and pre-PASS checks be
    deleted with the tests still green; this one only goes bad once the run is under way."""
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() H.idle(20) end } }')
    lua.execute("""
        W.obs_status = { registered = 3 }
        W.on_frame = function(f)
            if f > 10 then W.obs_status = { registered = 3, dropped = 5 } end
        end
    """)
    ok, log, _err = _shadow_run(lua, world, play, legs)
    assert "RESULT: FAIL" in log
    assert "dropped=5" in log
    assert "during one" in log, "the post-leg check is what should have caught this"


def test_an_observer_with_no_status_is_refused(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    lua.execute("""
        H.observer = function(result)
            return { poll = function() end }      -- no status()
        end
    """)
    try:
        ok, log, _err = _shadow_run(lua, world, play, legs)
    finally:
        lua.execute("H.observer = H_OBSERVER_ORIG")
    assert "RESULT: FAIL" in log
    assert "no status()" in log


def test_the_frame_hook_is_removed_even_when_a_leg_fails(lua, world):
    """A hook that outlives the run keeps polling a finished observer."""
    play = _bind(lua)
    legs = lua.execute(
        'return { { name = "boom", run = function() H.finish(false, "leg blew up") end } }')
    ok, log, _err = _shadow_run(lua, world, play, legs)
    assert "RESULT: FAIL leg blew up" in log
    assert world.unregistered == "hook-1", "the frame-end hook survived a failing leg"


def test_a_binding_whose_registration_returns_nothing_fails_the_run(lua, world):
    """`id or name` used to fabricate a handle here, which then went to unregisterbyid."""
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    world.reject_hook = True
    ok, log, _err = _shadow_run(lua, world, play, legs)
    assert "the frame-end poll could not be registered" in log


# -- the per-leg savestates --------------------------------------------------------------------


def test_each_finished_leg_saves_exactly_one_named_state(lua, world):
    play = _bind(lua)
    legs = lua.execute(
        'return { { name = "one", run = function() end },'
        '         { name = "skipped", open = true, open_reason = "not scripted" },'
        '         { name = "two", run = function() end } }')
    world.guard(lua.eval('function(p, L) return p.main(L,'
                         ' { name = "fake", save_states = "slink_fr_" }) end'), play, legs)
    assert list(world.saved.values()) == ["D:/states/slink_fr_one.State",
                                          "D:/states/slink_fr_two.State"]


def test_a_failed_leg_saves_nothing(lua, world):
    """A state written mid-failure is a trap: it looks like a checkpoint and is a wreck."""
    play = _bind(lua)
    legs = lua.execute(
        'return { { name = "boom", run = function() H.finish(false, "nope") end } }')
    world.guard(lua.eval('function(p, L) return p.main(L,'
                         ' { name = "fake", save_states = "slink_fr_" }) end'), play, legs)
    assert len(world.saved) == 0


def test_no_states_are_saved_when_the_run_does_not_ask_for_them(lua, world):
    play = _bind(lua)
    legs = lua.execute('return { { name = "one", run = function() end } }')
    world.guard(lua.eval('function(p, L) return p.main(L, { name = "fake" }) end'), play, legs)
    assert len(world.saved) == 0


# == Codex cx-93926f12 (final review of round 5) ==============================================


def test_rest_is_not_claimed_while_the_map_is_unreadable(lua, world):
    """H.pos reports (-1,-1) exactly when the SaveBlock pointer is unreadable, so a coordinate
    comparison made without checking the map can "arrive" at a tile the game cannot report."""
    play = _bind(lua)
    world.map_unreadable = True
    world.x, world.y = 4, 5
    assert play.wait_at(None, 4, 5, 30) is False


def test_rest_is_not_claimed_while_the_player_is_still_sliding(lua, world):
    """The tile matches for the whole budget, but the binding says the sprite never stopped."""
    play = _bind(lua)
    world.x, world.y = 4, 5
    world.sliding = True
    assert play.wait_at(None, 4, 5, 30) is False


def test_rest_is_not_claimed_when_the_budget_simply_runs_out(lua, world):
    """The old version returned a bare coordinate match on exhaustion, which reported arrival
    for a player who had only just got there -- or never had."""
    play = _bind(lua)
    lua.execute("W.on_frame = function(f) if f >= 28 then W.x, W.y = 4, 5 end end")
    assert play.wait_at(None, 4, 5, 30) is False, "four stable samples were never taken"


def test_rest_is_accepted_when_it_arrives_before_the_budget_ends(lua, world):
    play = _bind(lua)
    lua.execute("W.on_frame = function(f) if f >= 10 then W.x, W.y = 4, 5 end end")
    assert play.wait_at(None, 4, 5, 60) is True


def test_follow_waits_out_a_door_exit_animation_then_walks(lua, world):
    """FR run 16: the leg began while the door-exit step was still in flight, one tile short."""
    play = _bind(lua, '{ p = { from = { 0, 0 }, dirs = { "Right" }, to = { 1, 0 } } }')
    world.x, world.y = 0, 1                       # mid-slide, one tile short
    # the slide LANDS once, then the world behaves normally
    lua.execute("W.on_frame = function(f)"
                " if f >= 12 and not W.landed then W.x, W.y = 0, 0; W.landed = true end end")
    ok, log, err = world.guard(play.follow, None, "p", "test")
    assert ok, f"{err}\n{log}"
    assert (world.x, world.y) == (1, 0)


def test_enter_warp_clears_dialogue_with_the_bindings_button(lua, world):
    """A library that presses A in a doorway only works on games where A is the dismiss
    button."""
    play = lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'return PL.bind(H, {{ state_dir = "D:/states",\n'
        f'  clear_dialogue = function() W.cleared = (W.cleared or 0) + 1;'
        f' H.tap("Select", 3, 13) end }})'
    )
    ok, detail = play.enter_warp(None, "Up", 3)
    assert not ok and "map never changed" in detail
    assert world.cleared and world.cleared >= 1, "the injected dialogue policy was never used"
    pressed = lua.eval(
        "function() local n = 0 for _, t in ipairs(W.seen_buttons) do"
        " if t.A then n = n + 1 end end return n end")()
    assert pressed == 0, "enter_warp pressed A behind the binding's back"


# == leaving a menu (RR lane r5b/r5c/r5d) =====================================================


def test_leaving_a_menu_keeps_dismissing_through_the_exit_textbox(lua, world):
    """on_field goes true while the menu's exit textbox is still up. Stopping on that early
    true left the textbox to eat the first press of the NEXT menu open, and every press after
    it landed one place off -- two lane runs read as a menu-order bug that was really this."""
    play = _bind(lua)
    world.on_field = False
    lua.execute("W.on_frame = function(f) if f >= 30 then W.on_field = true end end")
    ok, log, err = world.guard(play.leave_menu, None, "pc", None)
    assert ok, f"{err}\n{log}"
    # the loop stops on the first on_field; the flush presses are the point
    assert world.backs >= 6, f"only {world.backs} back presses: the textbox flush is missing"


def test_leaving_a_menu_fails_when_the_field_never_appears(lua, world):
    play = _bind(lua)
    world.on_field = False
    ok, log, _err = world.guard(play.leave_menu, None, "pc", None)
    assert not ok
    assert "never got back to the field from the menu" in log


def test_leaving_a_menu_fails_when_the_field_does_not_hold(lua, world):
    """A field that appears and then goes away again is not a field we left a menu into."""
    play = _bind(lua)
    lua.execute("""
        W.on_field = true
        W.on_frame = function(f) if f >= 20 then W.on_field = false end end
    """)
    ok, log, _err = world.guard(play.leave_menu, None, "pc", None)
    assert not ok
    assert "the field did not hold after leaving the menu" in log


def test_the_back_button_is_the_bindings(lua, world):
    play = lua.execute(
        f'local PL = dofile("{_PLAYLIB}")\n'
        f'return PL.bind(H, {{ state_dir = "D:/states" }})'          # no menu_back
    )
    ok, log, _err = world.guard(play.leave_menu, None, "pc", None)
    assert not ok
    assert "no opts.menu_back" in log


def test_a_step_that_ends_in_a_battle_is_reported_as_such_not_as_a_stall(lua, world):
    """With enc=false the caller owns whatever battle happens. PHYSICAL (FR run 17): the
    encounter fired DURING a Down step of the grass hunt, the step fell through to tapping
    dialogue at a battle intro until its attempts ran out, and the hunt reported a stall while
    the observer was logging battle_begin -- eight begins against seven ends."""
    play = _bind(lua)
    lua.execute("W.on_move = function() W.in_battle = true end "
                "W.blocked = false")
    # the step lands AND a battle starts: landing wins, the hunt sees the battle next time round
    assert play.step(None, "Right", 100, None, False) is True

    world.reset()
    lua.execute("W.blocked = true "
                "W.on_frame = function(f) if f >= 14 then W.in_battle = true end end")
    ok, why = play.step(None, "Right", 100, None, False)
    assert ok is False
    assert why == "in_battle", f"reported {why!r}, so the caller would call it a stall"

    world.reset()
    lua.execute("W.blocked = true")
    ok, why = play.step(None, "Right", 100, None, False)
    assert ok is False and why == "stalled"


def test_gen3_facing_readers_take_the_low_nibble():
    """pret include/global.fieldmap.h:254-255 declares `u8 facingDirection:4; u8 movementDirection:4;`
    at ObjectEvent+0x18, packed LSB-first: the LOW nibble is facing, the high one is the movement
    direction (they differ while facingDirectionLocked). OMP C4-FACE found three `>> 4` readers."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    for rel in ("lua/tests/gen3_scripted_play.lua", "lua/tests/probe_gen3_battle_census.lua",
                "lua/tests/duo/duo_gen3_main.lua"):
        src = (root / rel).read_text(encoding="utf-8")
        for line in src.splitlines():
            if "+ 0x18)" in line and "read_u8" in line:
                assert ">> 4" not in line, f"{rel}: facing read from the high nibble: {line.strip()}"
