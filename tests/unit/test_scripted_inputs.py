"""Pure model controls for bounded input orchestration; no emulator or game memory."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

MODULE = Path(__file__).resolve().parents[2] / "lua/scripted_inputs.lua"


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().S = runtime.execute(MODULE.read_text(encoding="utf-8"))
    runtime.execute('''
        frame, calls, held = 0, 0, {}
        host = S.new{frame=function() return frame end, idle={A=false,B=false},
            step=function(buttons) calls=calls+1;held[calls]=buttons;frame=frame+1 end}
        spec={name="model",terminal="done",max_frames=10,max_phase_frames=10,terminal_idle=true}
    ''')
    return runtime


def test_exact_frame_phase_receipts_and_terminal_idle(lua):
    result = lua.execute('''
        local observed={}
        local result=host.run(spec,function(frame,n)
            return {A=true},n==3 and "done" or "walk",{at=n}
        end,function(name,phase,frame,point) observed[#observed+1]=point.at end)
        assert(calls==3 and not held[3].A and held[1].A and held[1].B==false)
        assert(#result.trace==2 and #observed==2 and observed[2]==3)
        return result
    ''')
    assert result["iterations"] == result["frames"] == 3


def test_terminal_requires_consecutive_observations_and_boot_can_finish_without_step(lua):
    result = lua.execute('''
        spec.settle_frames=3;spec.terminal_idle=false
        return host.run(spec,function(frame,n) return {},n==3 and "not-ready" or "done" end)
    ''')
    assert result["iterations"] == 6 and result["frames"] == 5


@pytest.mark.parametrize("setup,body,match", [
    ("spec.max_phase_frames=2", 'return {},"waiting"', "phase made no bounded progress"),
    ("spec.max_frames=4;spec.max_phase_frames=4", 'return {},n%2==0 and "one" or "two"', "route made no bounded progress"),
    ("", 'return {Reset=true},"done"', "input button"),
    ("", 'return {A=1},"done"', "input button"),
    ("", 'return {},nil', "phase name"),
    ("", 'frame=frame+1;return {},"done"', "driver advanced"),
    ("", 'return {},"done",{},{}', "request handler required"),
])
def test_invalid_driver_or_bounds_never_return_success(lua, setup, body, match):
    with pytest.raises(Exception, match=match):
        lua.execute(setup + ';return host.run(spec,function(f,n) ' + body + ' end)')


def test_request_needs_explicit_acknowledgement_before_any_step(lua):
    with pytest.raises(Exception, match="not acknowledged"):
        lua.execute('return host.run(spec,function() return {},"done",{},{} end,nil,function() return false end)')
    assert lua.globals().calls == 0
    result = lua.execute('return host.run(spec,function() return {},"done",{},{} end,nil,function() return true end)')
    assert result["requests"] == 1 and result["frames"] == 1


@pytest.mark.parametrize("delta", [0, 2])
def test_step_must_advance_exactly_one_frame(lua, delta):
    with pytest.raises(Exception, match="exactly one"):
        lua.execute(f'local h=S.new{{frame=function() return frame end,idle={{A=false}},step=function() frame=frame+{delta} end}}; h.idle(1)')


@pytest.mark.parametrize("frames", [-1, 1.5, 1000001])
def test_idle_bound_refuses_before_advancing(lua, frames):
    with pytest.raises(Exception, match="idle frame bound"):
        lua.globals().host.idle(frames)
    assert lua.globals().calls == 0


def test_missing_budget_and_phase_trace_overrun_refuse(lua):
    with pytest.raises(Exception, match="phase frame bound"):
        lua.execute('spec.max_phase_frames=nil;host.run(spec,function() return {},"done" end)')
    with pytest.raises(Exception, match="trace bound"):
        lua.execute('spec.max_phase_frames=10;spec.max_phase_changes=1;host.run(spec,function(f,n) return {},n==1 and "a" or "b" end)')
