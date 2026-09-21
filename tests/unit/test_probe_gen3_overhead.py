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


def test_realtime_gate_uses_fps_floor_and_wall_delta(module):
    lua, probe = module
    def samples(ms):
        return lua.table_from([ms] * 5)
    assert probe.realtime_ok(samples(10000), samples(10050))  # 59.70 fps
    assert not probe.realtime_ok(samples(10000), samples(10100))  # 59.41 fps
    assert not probe.realtime_ok(samples(9000), samples(10000))  # fps fine, >5% cost
    assert not probe.realtime_ok(samples(10200), samples(10000))  # baseline misses floor
    assert probe.fps(0) == 0  # unthrottled wall tick unavailable, never infinity


def test_hooks_only_discard_sink_prevents_queue_overflow(module):
    lua, probe = module
    lua.execute("signals={pending={}}; counts={}")
    g = lua.globals()
    probe.discard_queue(g.signals, g.counts)
    lua.execute("for i=1,3000 do signals.pending[#signals.pending+1]={kind='frame_control'} end")
    assert len(g.signals.pending) == 0
    assert g.counts.frame_control == 3000


def test_breakdown_configuration_and_registration_contract():
    assert 'os.getenv("SLINK_OVERHEAD_THROTTLE")=="1"' in SOURCE
    assert '{"A","E","B","C","D","F","G","H"}' in SOURCE
    assert 'label=="F" or label=="H"' in SOURCE
    assert 'label=="G" or label=="H" then observer.parts.signals:close()' in SOURCE
    assert '{frame_control=assert(observer.parts.sites.frame_control)}' in SOURCE
    assert 'if hooks_only then P.discard_queue' in SOURCE
    assert 'signature==canonical' in SOURCE
    assert 'client.get_approx_framerate()' in SOURCE
    assert 'P.realtime_ok(base.wall,measured.wall)' in SOURCE
    assert 'INFORMATIONAL speed=6399' in SOURCE
