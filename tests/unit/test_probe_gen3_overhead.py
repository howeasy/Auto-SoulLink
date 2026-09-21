"""Pure arithmetic and source wiring; real timings require the coordinator lane."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
SOURCE = (Path(__file__).resolve().parents[2] / "lua/tests/probe_gen3_overhead.lua").read_text(encoding="utf-8")


@pytest.fixture
def module():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("memory={}; emu={}; event={}; client={}; console={log=function() error('unexpected log') end}")
    return lua, lua.execute(SOURCE)


def test_median_and_budget(module):
    lua, probe = module
    baseline = lua.table_from([100, 101, 99, 400, 98])
    assert probe.median(baseline) == 100
    assert baseline[1] == 100 and baseline[4] == 400
    assert probe.median(lua.table_from([4, 2])) == 3
    assert probe.within(baseline, lua.table_from([104] * 5))
    assert probe.within(baseline, lua.table_from([105] * 5))
    assert not probe.within(baseline, lua.table_from([106] * 5))
    assert probe.delta(baseline, lua.table_from([110] * 5)) == pytest.approx(10)


@pytest.mark.parametrize("samples", [[], [0], [-1]])
def test_invalid_measurement_refused(module, samples):
    lua, probe = module
    with pytest.raises(lupa.LuaError):
        probe.median(lua.table_from(samples))


def test_window_measures_exact_frame_count(module):
    lua, probe = module
    lua.execute("n=0; advance=function() n=n+1 end; clock=function() return n/1000 end; wall=function() return math.floor(n/1000) end")
    g = lua.globals()
    cpu_ms, wall_ms = probe.window(g.advance, g.clock, g.wall, 600)
    assert g.n == 600 and cpu_ms == pytest.approx(600) and wall_ms == 0
    assert probe.FRAMES == 600 and probe.WINDOWS == 5


def test_no_console_output_in_window_and_real_observer_wired():
    body = SOURCE.split("function P.window", 1)[1].split("function P.within", 1)[0]
    assert "console.log" not in body and "G.log" not in body and "G.phase" not in body
    timed = SOURCE.split("for i=1,P.WINDOWS do", 1)[1].split("local st=", 1)[0]
    assert "console.log" not in timed and "G.log" not in timed
    assert 'dofile(wt.."/lua/gen3/shadow_run.lua")' in SOURCE
    assert "Shadow.start({shadow=true" in SOURCE and "observer.poll()" in SOURCE
    assert "observer.teardown()" in SOURCE and "event.unregisterbyid(id)" in SOURCE
    assert '{{"B","A"},{"C","E"},{"D","E"}}' in SOURCE
    assert 'label=="E" or label=="C"' in SOURCE
    assert 'if label=="D" then register' in SOURCE
    assert "wire_deltas=UNVERIFIED" in SOURCE
