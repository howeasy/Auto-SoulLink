"""T2/A2 carrier at its public returned-function boundary; no emulator or game-data writes."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

SOURCE = (Path(__file__).resolve().parents[2] /
          "lua/tests/duo/scenario_gen3_battle_window.lua")

MODEL = r"""
function world(mode, fault)
    local frame, rx, attempted = 10, 0, 0
    local slot = mode == 'trainer_bench' and 1 or 0
    local hp, battling, outcome = 20, false, 0
    local ready, exiting, finished, prepared = false, false, false, false
    local records, hooks, watchers, logs = {}, {}, {}, {}
    local active_bytes = string.rep('A', 0x58)
    local target_slot, target_key = slot, 'K'
    local c = {D={battle_window_case=mode}, player='a', cp={}}
    local function write(reason)
        attempted = attempted + 2
        hp = 0
        if fault == 'wrong_key' then target_key = 'OTHER' end
        if fault == 'wrong_slot' then target_slot = 3 end
        if fault == 'active_record' then active_bytes = string.rep('B', 0x58) end
        local w = {reason=reason, address=0x02024284 + slot*100 + 0x56, len=2, frame=frame}
        if fault == 'wrong_address' then w.address = w.address + 100 end
        if fault == 'wrong_length' then w.len = 100 end
        if fault == 'wrong_frame' then w.frame = frame - 1 end
        records[#records+1] = w
        if hooks[reason] then local f=hooks[reason]; hooks[reason]=nil; f('write') end
    end
    c.frames = function(n)
        for _=1,n do
            frame = frame + 1
            if ready and rx == 0 and fault ~= 'no_rx' then
                rx = 1
                if fault=='natural_end' then battling=false; outcome=4 end
                if mode == 'trainer_bench' then
                    if fault == 'late_bench' then battling=false; outcome=1 end
                    if fault ~= 'no_write' then write('battle_faint') end
                    if fault == 'extra_write' then attempted=attempted+2 end
                    if fault == 'duplicate_rx' then rx=2 end
                elseif fault == 'active_mutated' then write('battle_faint') end
            end
            if ready and rx > 0 and mode == 'active_end' and fault == 'last_hold_frame' and frame == 131 then
                write('battle_faint')
            end
            for _,fn in ipairs(watchers) do fn() end
        end
    end
    c.log = function(s) logs[#logs+1]=s; if s:find('^READY_BATTLE_WINDOW') then ready=true end end
    c.wait_go = function() return fault ~= 'no_go' end
    c.linked = function() return 'K' end
    c.find = function(k) if k == target_key then return {key=k,slot=target_slot,hp=hp} end end
    c.party = function() return {{slot=0,level=fault=='prep_floor' and 6 or (prepared and 13 or 9),
        hp=fault=='prep_unhealed' and 19 or 20,max_hp=20,status=fault=='prep_status' and 8 or 0}} end
    c.received = function(cmd,k) return k == 'K' and rx or 0 end
    c.in_battle = function() return battling end
    c.battler_slot = function() return fault=='prep_switched' and 1 or 0 end
    c.battle_hold = function(k)
        if k=='K' and battling and rx>0 and fault~='missing_hold' then return {why='active battler'} end
    end
    c.attempted = function() return attempted end
    c.write_lines = function() return records end
    c.on_write = function(reason,fn) hooks[reason]=fn end
    c.watch = function(fn) watchers[#watchers+1]=fn end
    c.battle_window_snapshot = function(k)
        if fault == 'snapshot_error' and ready then error('unreadable bus') end
        return {frame=frame, samples=frame, in_battle=battling, outcome=outcome,
                is_trainer=mode=='trainer_bench', trainer_id=fault=='wrong_trainer' and 104 or 102,
                battlers_count=2, active_slots=fault=='two_slots' and {0,2} or {0},
                party_base=fault=='unaligned' and 0x02024285 or 0x02024284,
                target_count=fault=='duplicate_key' and 2 or 1,
                target={key=target_key,slot=target_slot,hp=hp},
                active_bytes=fault=='short_record' and string.rep('A',0x57) or active_bytes,
                battle_permit=battling and not (ready and fault=='denied_battle_write'),
                overworld_permit=not battling and fault~='denied_field_write',
                tuple=fault=='empty_tuple' and '' or 'main=selection comm0=1 flags=1 controller=player'}
    end
    c.enter_trainer = function(label,id,prep)
        assert(id==102 and prep.level_floor==13 and prep.max_frames==60000)
        prepared=true
        if fault=='prep_hp' then hp=hp-1 end
        if fault=='prep_slot' then target_slot=3 end
        if fault=='prep_transient' then hp=19; c.frames(1); hp=20 end
        if fault=='prep_switched' then battling=true; c.frames(1) end
        if fault=='route_failed' then return false,'blocked on normal route' end
        battling=true
        return true
    end
    c.hunt = function() battling=true; return true end
    c.SP={verify_fight_cursor=function() return 'fight' end}
    c.try=function(fn,...) return pcall(fn,...) end
    c.play={fight_through=function()
        finished=true; c.frames(1); battling=false; outcome=fault=='trainer_whiteout' and 2 or 1; c.frames(1)
    end,wait_scene_settled=function() c.frames(1) end}
    c.run_away=function()
        exiting=true
        c.frames(1)
        if fault=='early_exit_write' then write('overworld') end
        battling=false; outcome=4
        -- The first field write may occur BEFORE the end-of-frame watcher notices the exit.
        if fault~='no_exit_write' then write('overworld') end
        c.frames(1)
        return true
    end
    c.wait_until=function(pred,secs,what)
        for _=1,250 do local v=pred(); if v then return v end; c.frames(1) end
    end
    c.save=function()
        if fault=='revived' then hp=20 end
        c.frames(1)
        return fault~='save_failed','save failed'
    end
    c.partner_result=function() return 'RESULT: PASS (idle)' end
    c.result=function() return table.concat(logs,'\n'),attempted,exiting,finished end
    return c
end
"""


def run(mode, fault=""):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MODEL)
    ctx = lua.globals().world(mode, fault)
    scenario = lua.execute(SOURCE.read_text(encoding="utf-8"))
    passed, why = scenario(ctx)
    return passed, why, ctx.result()


@pytest.mark.parametrize("mode,fault,reason", [
    ("active_end", "active_mutated", "active target mutated"),
    ("trainer_bench", "wrong_key", "wrong key/slot"),
    ("trainer_bench", "wrong_slot", "wrong key/slot"),
    ("trainer_bench", "late_bench", "outside the in-battle bench window"),
])
def test_first_falsifiers_refuse_wrong_target_or_wrong_phase(mode, fault, reason):
    passed, why, (log, *_) = run(mode, fault)
    assert "READY_BATTLE_WINDOW" in log  # fail on the observed defect, not setup
    assert passed is False and reason in why, (fault, why)
    assert "BATTLE_WINDOW_SAVED" not in log


@pytest.mark.parametrize("mode", ["trainer_bench", "active_end"])
def test_real_carrier_accepts_keyed_write_in_its_own_phase_and_normal_save(mode):
    passed, why, (log, attempted, exiting, finished) = run(mode)
    assert passed is True, (why, log)
    assert attempted == 2
    assert exiting == (mode == "active_end")
    assert finished == (mode == "trainer_bench")
    assert log.index("READY_BATTLE_WINDOW") < log.index("BATTLE_WINDOW_LANDED")
    assert log.index("BATTLE_WINDOW_LANDED") < log.index("BATTLE_WINDOW_SAVED")
    if mode == "active_end":
        assert log.index("BATTLE_WINDOW_HELD") < log.index("BATTLE_WINDOW_EXIT_INPUT")
        assert log.index("BATTLE_WINDOW_EXIT_INPUT") < log.index("BATTLE_WINDOW_EXIT active_end")
        assert log.index("BATTLE_WINDOW_EXIT active_end") < log.index("BATTLE_WINDOW_LANDED")
        assert "reason=overworld" in log
    else:
        assert "trainer=102" in log and "reason=battle_faint" in log
        assert log.index("BATTLE_WINDOW_LANDED") < log.index("BATTLE_WINDOW_EXIT trainer_bench")
        assert "active_hex=" in log and "samples=" in log and "PREP_LEVEL before=9 after=13" in log
        assert "hp=full status=none" in log


@pytest.mark.parametrize("mode,fault,reason", [
    ("trainer_bench", "wrong_address", "write address/length/frame"),
    ("trainer_bench", "wrong_length", "write address/length/frame"),
    ("trainer_bench", "wrong_frame", "write address/length/frame"),
    ("trainer_bench", "active_record", "active battle record changed"),
    ("trainer_bench", "extra_write", "extra client write"),
    ("trainer_bench", "duplicate_rx", "duplicate force_faint"),
    ("trainer_bench", "denied_battle_write", "outside the in-battle bench window"),
    ("trainer_bench", "no_write", "no witnessed"),
    ("trainer_bench", "trainer_whiteout", "T2_RNG_LOSS"),
    ("active_end", "missing_hold", "not held in battle_pending"),
    ("active_end", "last_hold_frame", "active target mutated"),
    ("active_end", "early_exit_write", "active target mutated"),
    ("active_end", "denied_field_write", "active target mutated"),
    ("active_end", "no_exit_write", "no witnessed"),
    ("active_end", "no_rx", "no fresh keyed"),
    ("active_end", "natural_end", "NOT_SUBJECT active_end"),
    ("trainer_bench", "snapshot_error", "observer error"),
    ("trainer_bench", "revived", "revived"),
    ("active_end", "save_failed", "save failed"),
])
def test_observed_failure_is_named_and_never_saved_as_a_pass(mode, fault, reason):
    passed, why, _ = run(mode, fault)
    assert passed is False and reason in why, (fault, why)


@pytest.mark.parametrize("fault,reason", [
    ("no_go", "no go-file"),
    ("route_failed", "trainer route"),
    ("wrong_trainer", "wrong trainer/type"),
    ("duplicate_key", "ambiguous target"),
    ("short_record", "unreadable battle snapshot"),
    ("unaligned", "unreadable battle snapshot"),
    ("empty_tuple", "unreadable battle snapshot"),
    ("two_slots", "readable single battle"),
    ("prep_hp", "PREPARATION altered"),
    ("prep_slot", "PREPARATION altered"),
    ("prep_floor", "level floor"),
    ("prep_transient", "PREPARATION altered"),
    ("prep_unhealed", "full HP with no status"),
    ("prep_status", "full HP with no status"),
    ("prep_switched", "bench switched in"),
])
def test_bad_setup_does_not_publish_ready(fault, reason):
    passed, why, (log, *_) = run("trainer_bench", fault)
    assert passed is False and reason in why
    assert "READY_BATTLE_WINDOW" not in log


@pytest.mark.parametrize("terminal,want", [("PASS", True), ("FAIL", False)])
def test_idle_peer_requires_a_terminal_partner_pass(terminal, want):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MODEL)
    ctx = lua.globals().world("active_end", "")
    ctx.player = "b"
    ctx.partner_result = lambda: f"noise\nRESULT: {terminal} (A)\n"
    scenario = lua.execute(SOURCE.read_text(encoding="utf-8"))
    passed, _ = scenario(ctx)
    assert passed is want
    log, attempted, exiting, finished = ctx.result()
    assert not log and attempted == 0 and not exiting and not finished
