"""scenario_gen3_ball_gate.lua post_flip leg waits for the client's 30-frame has_pokeballs latch.

Final cut b6cd75c6, frlgc_ball_gate_gen3_{fr,lg}_as_a_companion: 'post-flip SYNTH stock was not read
back'. The stock was in the bag (balls=20) but the check ran on the first field frame, before the
client's next 30-frame tick latched has_pokeballs (lua/gen3/client.lua latch_balls). Driven over a fake
ctx through lupa, no emulator.
"""
from __future__ import annotations

import os

from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SCENARIO = os.path.join(_REPO, "lua", "tests", "duo", "scenario_gen3_ball_gate.lua")

_DRIVER = """
local scenario = dofile(SCENARIO)
local function run(balls, latch_after_polls)
    local polls = 0
    local ctx = { D = { ball_stock_phase = true, phase = "post_flip", wt = WT }, session = { state = { has_pokeballs = false } },
                  wait_go = function() return true end, balls = function() return balls end,
                  jlog = function() end, log = function() end, catch = function() return nil, "stop" end }
    function ctx.wait_until(pred, secs, what)
        for _ = 1, 3 do
            polls = polls + 1
            if latch_after_polls and polls >= latch_after_polls then ctx.session.state.has_pokeballs = true end
            if pred() then return true end
        end
        return false
    end
    local ok, a, b = pcall(scenario, ctx)
    return ok, a, b, polls
end
return run
"""


def _run(balls, latch_after_polls):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SCENARIO = _SCENARIO
    lua.globals().WT = _REPO
    ok, result, why, polls = lua.execute(_DRIVER)(balls, latch_after_polls)
    return ok, result, why, polls


def test_a_flag_that_latches_after_the_first_poll_is_waited_for():
    # past the stock check the scenario dofile()s the link scenario, which this fake ctx cannot run:
    # any failure there is fine, the stock-check failure is not
    ok, result, why, polls = _run(20, 2)
    assert polls >= 2
    assert "SYNTH stock was not read back" not in str(why) and "SYNTH stock was not read back" not in str(result)


def test_a_flag_that_never_latches_fails_by_name():
    ok, result, why, _ = _run(20, None)
    assert ok and result is False and why == "post-flip SYNTH stock was not read back"


def test_wrong_stock_fails_without_waiting():
    ok, result, why, polls = _run(19, 1)
    assert ok and result is False and why == "post-flip SYNTH stock was not read back" and polls == 0
