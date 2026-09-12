from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime


@pytest.fixture
def lua():
    result = LuaRuntime(unpack_returned_tuples=True)
    result.globals().package.path = (
        (Path(__file__).resolve().parents[2] / "lua/?.lua").as_posix()
        + ";"
        + result.globals().package.path
    )
    result.execute(
        "time=0;Pacer=require('frame_pacer');pacer=Pacer.new({clock=function()return time end,numerator=262144,denominator=4389});period=4389/262144"
    )
    return result


def test_fractional_cartridge_clock_does_not_run_early_or_twice_at_one_time(lua):
    assert lua.eval("pacer:take(true,false)")
    assert not lua.eval("pacer:take(true,false)")
    lua.execute("time=period-0.000001")
    assert not lua.eval("pacer:take(true,false)")
    lua.execute("time=period")
    assert lua.eval("pacer:take(true,false)")


@pytest.mark.parametrize("permitted,paused", [(False, False), (True, True), (False, True)])
def test_pause_and_lost_authority_discard_time_debt(lua, permitted, paused):
    assert lua.eval("pacer:take(true,false)")
    lua.globals().time = 100
    assert not lua.globals().pacer.take(lua.globals().pacer, permitted, paused)
    assert lua.eval("pacer:take(true,false)")
    assert not lua.eval("pacer:take(true,false)")


def test_long_stall_never_creates_a_burst_of_catchup_frames(lua):
    assert lua.eval("pacer:take(true,false)")
    lua.globals().time = 100
    assert lua.eval("pacer:take(true,false)")
    assert all(not lua.eval("pacer:take(true,false)") for _ in range(100))


def test_clock_failure_latches_the_scheduler(lua):
    lua.globals().time = 1
    assert lua.eval("pacer:take(true,false)")
    lua.globals().time = 0.5
    assert lua.eval("pacer:take(true,false)")[0] is False
    lua.globals().time = 2
    assert lua.eval("pacer:take(true,false)")[0] is False


@pytest.mark.parametrize("value", ["0", "-1", "true", "1.5", "1000000001"])
def test_invalid_video_clock_is_refused(lua, value):
    assert (
        lua.eval(
            "pcall(function()Pacer.new({clock=function()return time end,numerator="
            + value
            + ",denominator=1})end)"
        )[0]
        is False
    )


@pytest.mark.parametrize("value", [1e20, 2**49])
def test_finite_clock_with_insufficient_precision_cannot_schedule_frames(lua, value):
    lua.globals().time = value
    allowed, reason = lua.eval("pacer:take(true,false)")
    assert allowed is False and "represent" in reason
    assert lua.eval("pacer:take(true,false)")[0] is False
    assert lua.eval("pacer:status().scheduled") == 0
