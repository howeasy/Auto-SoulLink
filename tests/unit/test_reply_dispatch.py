"""Neutral reply pump controls (MODEL): injected source/codec/validator/handler, lupa only."""

from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]

WORLD = """
local factory, budget = ...
local w = {lines={}, handled={}, errors={}, received=0}
w.policy = {
    budget = budget,
    receive = function()
        if w.receive_error then error('socket gone') end
        w.received = w.received + 1
        return table.remove(w.lines, 1)
    end,
    decode = function(line)
        if line == 'garbage' then error('bad json') end
        return w.envelopes[line]
    end,
    validate = function(env)
        if type(env) == 'table' and type(env.commands) == 'table' then return env.commands end
        return nil, 'no command list'
    end,
    handle = function(cmd)
        if cmd == 'boom' then error('handler failed') end
        if cmd == 'reenter' then w.reentry = {pcall(w.pump.step, w.pump)} end
        w.handled[#w.handled + 1] = cmd
    end,
    on_error = function(stage, why)
        w.errors[#w.errors + 1] = stage
        if w.error_throws then error('logger down') end
    end,
}
w.envelopes = {
    a={commands={'a1', 'a2'}}, b={commands={'b1'}}, c={commands={'c1'}},
    sparse={commands={'s1', nil, 's3'}}, keyed={commands={'k1', x='k2'}},
    shape={other=true}, mixed={commands={'m1', 'boom', 'm3'}}, reenter={commands={'reenter', 'r2'}},
    empty={commands={}},
}
w.pump = factory.new(w.policy)
return w
"""


def world(budget=None, lines=()):
    lua = LuaRuntime(unpack_returned_tuples=True)
    factory = lua.eval("dofile")((ROOT / "lua/reply_dispatch.lua").as_posix())
    w = lua.execute(WORLD, factory, lua.eval("math.huge") if budget is None else budget)
    for i, line in enumerate(lines, 1):
        w.lines[i] = line
    return lua, w


def step(w):
    return w.pump.step(w.pump)


def handled(w):
    return list(w.handled.values())


def errors(w):
    return list(w.errors.values())


@pytest.mark.parametrize("line", ["sparse", "keyed", "shape", "garbage"])
def test_a_malformed_or_sparse_envelope_dispatches_nothing_and_the_next_line_still_runs(line):
    _lua, w = world(lines=[line, "b"])
    assert step(w) == (2, False)
    assert handled(w) == ["b1"]
    assert errors(w) == ["decode" if line == "garbage" else "validate"]


def test_a_handler_error_never_aborts_the_other_commands_or_lines():
    _lua, w = world(lines=["mixed", "b"])
    step(w)
    assert handled(w) == ["m1", "m3", "b1"] and errors(w) == ["handle"]


def test_a_throwing_error_reporter_is_contained():
    _lua, w = world(lines=["mixed", "garbage", "b"])
    w.error_throws = True
    step(w)
    assert handled(w) == ["m1", "m3", "b1"] and errors(w) == ["handle", "decode"]


def test_the_budget_bounds_pulls_and_leaves_unread_lines_in_order():
    _lua, w = world(budget=2, lines=["a", "b", "c", "empty"])
    assert step(w) == (2, True)
    assert handled(w) == ["a1", "a2", "b1"] and w.received == 2
    assert list(w.lines.values()) == ["c", "empty"]
    assert step(w) == (2, True)
    assert step(w) == (0, False)
    assert handled(w) == ["a1", "a2", "b1", "c1"]


def test_an_unbounded_budget_drains_everything_queued():
    _lua, w = world(lines=["a", "b", "c"])
    assert step(w) == (3, False) and handled(w) == ["a1", "a2", "b1", "c1"]


def test_reentrant_pumping_from_a_handler_is_refused_and_order_is_kept():
    _lua, w = world(lines=["reenter", "b"])
    step(w)
    assert w.reentry[1] is False and "reentrant" in str(w.reentry[2])
    assert handled(w) == ["reenter", "r2", "b1"]


def test_a_transport_error_propagates_and_the_pump_stays_usable():
    _lua, w = world(lines=["a"])
    w.receive_error = True
    with pytest.raises(LuaError, match="socket gone"):
        step(w)
    w.receive_error = False
    assert step(w) == (1, False) and handled(w) == ["a1", "a2"]


@pytest.mark.parametrize("budget", [0, -1, 1.5, "3"])
def test_the_budget_must_be_explicit_and_positive(budget):
    lua = LuaRuntime(unpack_returned_tuples=True)
    with pytest.raises(LuaError, match="budget"):
        world(budget=budget)
    with pytest.raises(LuaError, match="budget"):
        lua.execute(WORLD, lua.eval("dofile")((ROOT / "lua/reply_dispatch.lua").as_posix()), lua.eval("nil"))


@pytest.mark.parametrize("name", ["receive", "decode", "validate", "handle", "on_error"])
def test_every_policy_callback_is_required(name):
    _lua, w = world()
    w.policy[name] = None
    with pytest.raises(LuaError, match=name):
        _lua.eval("dofile")((ROOT / "lua/reply_dispatch.lua").as_posix()).new(w.policy)
