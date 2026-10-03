"""MODEL replays for the non-qualifying Gen 4 diagnostic driver; never an emulator."""
from pathlib import Path

import lupa
import pytest

from tools import gen4_diag as d


def api():
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().G4_DIAG_TEST = True
    runtime.globals().SLINK_GEN4_PROBE_TEST = True
    runtime.globals().PROBE = runtime.execute((d.REPO / "lua/tests/probe_gen4_hooks.lua").read_text())
    runtime.globals().DIAG = runtime.execute(d.LUA)
    return runtime


def test_fight_uses_exact_frozen_recipe_and_does_not_invent_turns():
    r = api()
    r.execute('''
      buttons={}; frame=0
      local title={profile={battle={}},symbols={x={address=4}},phase_cases={}}
      local leg={name="model",max_frames=5,steps={{press={"A"},hold_frames=2,then_wait_frames=3}},
        ["until"]={symbol="x",deref={},offset=0,value=1}}
      result=DIAG.fight(PROBE,title,leg,function() return frame==5 and 1 or 0 end,
        function(b) frame=frame+1; buttons[#buttons+1]=b.A==true end,function() return frame end)
      assert(frame==5 and #buttons==5 and buttons[1] and buttons[2] and not buttons[3]
        and not buttons[4] and not buttons[5])
      assert(leg.max_frames==5 and leg.steps[1].hold_frames==2 and leg.steps[1].then_wait_frames==3)
      assert(result.recipes[1].outcome=="until_met" and result.recipes[1].frames_used==5)
      assert(result.rng.status=="INCONCLUSIVE" and result.turn_count_available==false)
    ''')


def test_driver_is_outside_every_qualification_surface():
    from tools import gen4_evidence as e
    for kind in e.SCRIPTS:
        for title in e.PACKS:
            paths = e.dependencies(kind, title)
            assert "tools/gen4_diag.py" not in paths
            assert "tests/unit/test_gen4_diag.py" not in paths
    assert Path(d.__file__).resolve() == d.REPO / "tools/gen4_diag.py"


def test_settle_is_uncensored_and_first_resident_sample_is_left_censored():
    r = api()
    r.execute('''
      local sites={{id="late",overlay_id=12,register_hex="aabb",address=20,extent=2}}
      local trace=DIAG.settle_trace(sites); local active=false; local pin="0000"
      local function sample(f) DIAG.settle_sample(trace,sites,function() return active end,
        function() return pin end,f) end
      sample(0); active=true; sample(1)
      for f=2,20 do sample(f) end
      pin="aabb"; sample(21)
      assert(#trace.samples==22 and trace.epochs[1].delta==20)
      assert(trace.epochs[1].status=="SETTLED" and trace.epochs[1].active_frame==1)
      local first=DIAG.settle_trace(sites)
      DIAG.settle_sample(first,sites,function() return true end,function() return "aabb" end,0)
      assert(first.epochs[1].status=="LEFT_CENSORED" and first.epochs[1].delta==nil)
      assert(DIAG.settle_verdict(first)=="OPEN" and DIAG.settle_verdict(trace)=="OBSERVED")
    ''')


def test_pp_deltas_are_ordinals_with_battler_and_move_identity():
    r = api()
    r.execute('''
      local out={pp_deltas={}}; local a={our_species=155,our_moves={33,43,0,0},our_pp={35,40,0,0},
        enemy_species=19,enemy_moves={33,39,0,0},enemy_pp={35,30,0,0},enemy_hp=17}
      local b={our_species=155,our_moves={33,43,0,0},our_pp={35,39,0,0},
        enemy_species=19,enemy_moves={33,39,0,0},enemy_pp={34,30,0,0},enemy_hp=13}
      DIAG.pp_delta(out,a,b,90)
      assert(#out.pp_deltas==2 and out.pp_deltas[1].slot==2 and out.pp_deltas[1].move_id==43)
      assert(out.pp_deltas[1].ordinal==1 and out.pp_deltas[1].battler=="our")
      assert(out.pp_deltas[2].slot==1 and out.pp_deltas[2].battler=="enemy")
      assert(out.pp_deltas[1].turn==nil)
      assert(#out.hp_changes==1 and out.hp_changes[1].before==17 and out.hp_changes[1].after==13
        and out.hp_changes[1].cause=="UNMEASURED")
    ''')


def test_boundary_preserves_callback_vs_post_advance_frame_parity():
    r = api()
    r.globals().REGISTRY = r.execute((d.REPO / "lua/hook_registry.lua").read_text())
    r.execute('''
      frame=7; wanted=true; callback=nil
      local site={id="exit",address=20,mode="thumb",fire_hex="01000000"}
      local binding={validate=function(s) return s end,register=function(s,cb) callback=cb; return "guid" end,
        unregister=function() return true end,capture=function(s)
          return {id=s.id,frame=frame,step_id=state.step_id} end}
      local composite=PROBE.composite(REGISTRY,binding)
      monitor,state=PROBE.phase_monitor(composite,"battle_close",{site},"exit",
        function() return wanted end,function() return true end,function() return frame end)
      monitor.before(); callback(20,1,0); wanted=false; frame=frame+1; monitor.after()
      monitor.before(); monitor.after(); monitor.finish()
      local b=state.close_boundaries[1]
      assert(b.producer_frames[1]==7 and b.fall_frame==8 and b.frame==8)
      assert(b.producer_steps[1]==b.fall_step_id and b.pending==1 and state.seen[1]==7)
      assert(#state.seen==1 and state.second_drain==0 and composite:live_handles()==0)
      result=DIAG.boundary_result(state,{7},{1},composite)
      assert(result.status=="OBSERVED" and result.frame_parity.callback_minus_fall==-1)
    ''')


@pytest.mark.parametrize("mode", ["timeout", "error"])
def test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode):
    import json
    class Process:
        pid = 412
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, timeout):
            if not self.stopped:
                raise d.subprocess.TimeoutExpired("model", timeout)
            return 0
    proc = Process()
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(d.g4, "kill_our_emuhawk", lambda lane: None)
    monkeypatch.setattr(d, "verify_after", lambda config: None)
    def service(*args):
        if mode == "error":
            raise ValueError("model planner error")
    monkeypatch.setattr(d, "service_bridge", service)
    cfg = {"qualified": False, "hashes": {}, "source_head": "model"}
    verdict = d.collect(cfg, tmp_path, ["owned-emulator", "--config="+str(tmp_path / "config.ini")],
                        planner=None, timeout=0 if mode == "timeout" else 2)
    out = json.loads((tmp_path / "diagnostic.json").read_text())
    assert proc.stopped and out["ownership"]["pid"] == 412
    assert out["ownership"]["exited"] and out["qualified"] is False
    assert verdict == 1 and out["status"] == "FAIL"
    assert ("timeout" if mode == "timeout" else "model planner error") in out["reason"]


@pytest.mark.parametrize("original,replacement,test", [
    ("pcall(M.play_recipe,leg,function(buttons)", "pcall(M.play_recipe,leg,function(buttons) buttons.A=not buttons.A;",
     test_fight_uses_exact_frozen_recipe_and_does_not_invent_turns),
    ("left_censored=prior==nil", "left_censored=false",
     test_settle_is_uncensored_and_first_resident_sample_is_left_censored),
    ("local active=resident(s.overlay_id)==true", "if frame>16 then return end; local active=resident(s.overlay_id)==true",
     test_settle_is_uncensored_and_first_resident_sample_is_left_censored),
    ("callback_minus_fall=f-b.fall_frame", "callback_minus_fall=0",
     test_boundary_preserves_callback_vs_post_advance_frame_parity),
])
def test_lua_controls_red_and_revert(monkeypatch, original, replacement, test):
    source = d.LUA
    assert source.count(original) == 1
    test()
    monkeypatch.setattr(d, "LUA", source.replace(original, replacement))
    with pytest.raises((AssertionError, lupa.LuaError)):
        test()
    monkeypatch.setattr(d, "LUA", source)
    test()


def test_generated_boundary_script_runs_real_monitor_with_frame_end_increment(tmp_path):
    """Execute the entire generated runtime, not just its pure helper functions."""
    import json
    import struct

    from tests.unit.test_gen4_battle_faint_model import BASE, SUB0, World
    title = json.loads((d.REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["heartgold"]
    case = next(c for c in title["phase_cases"] if c["name"] == "battle_close")
    producer = title["sites"][case["producer_site"]]
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"lane": tmp_path.as_posix(), "artifact": title, "command": "boundary",
                                 "phase_case": case, "state_path": "model",
                                 "producer_word": int(producer["fire_hex"], 16)}))
    world = World()
    r = lupa.LuaRuntime(unpack_returned_tuples=True)
    r.globals().CONFIG = config.as_posix()
    r.globals().ROOT = d.REPO.as_posix()
    r.globals().PIN = producer["register_hex"]
    r.globals().SITE = producer["address"]
    r.globals().WORD = int(producer["fire_hex"], 16)
    r.globals().PC = producer["address"] + 4
    r.globals().READ = lambda a, bus: struct.unpack_from("<I", world.m, a - BASE)[0]
    r.globals().FALL = lambda: world.w32(SUB0 + 4, 0)
    r.execute('''
      local original=os.getenv
      os.getenv=function(key) if key=="SLINK_ROOT" then return ROOT elseif key=="G4_DIAG_CONFIG" then return CONFIG end; return original(key) end
      frame=7; callbacks={}
      memory={read_u32_le=READ,read_bytes_as_array=function(a,n)
        assert(a==SITE); local bytes={}; for i=1,n do bytes[i]=tonumber(PIN:sub(i*2-1,i*2),16) end; return bytes end}
      event={on_bus_exec=function(cb,a,name,bus) callbacks[name]=cb; return name end,
        unregisterbyid=function(h) callbacks[h]=nil; return true end}
      emu={framecount=function() return frame end,getregister=function() return PC end,
        frameadvance=function() for _,cb in pairs(callbacks) do cb(SITE,WORD,0) end; FALL(); frame=frame+1 end}
      joypad={set=function() end}; savestate={load=function() end}; client={exit=function() end}
    ''')
    r.execute(d.LUA)
    observed = json.loads((tmp_path / "observation.json").read_text())
    assert observed["status"] == "OBSERVED", observed
    assert observed["frame_parity"]["callback_minus_fall"] == -1
    assert observed["retained"] == 0 and observed["state"]["pending_at_close"] == 1
    assert observed["qualified"] is False


@pytest.mark.parametrize("mode", ["timeout", "error"])
def test_cleanup_control_red_and_revert(tmp_path, monkeypatch, mode):
    source = Path(d.__file__).read_text()
    assert source.count("proc.terminate()") == 1
    namespace = {"__file__": d.__file__}
    exec(compile(source.replace("proc.terminate()", "pass # removed terminate control"), d.__file__, "exec"), namespace)
    original = d.collect
    test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(d, "collect", namespace["collect"])
    with pytest.raises(AssertionError):
        test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(d, "collect", original)
    test_owned_process_cleanup_and_error_publication(tmp_path, monkeypatch, mode)
