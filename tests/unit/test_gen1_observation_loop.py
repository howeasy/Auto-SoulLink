"""Sequencing proof for lua/gen1_observation_loop.lua under stubbed BizHawk globals.

Only tick() is driven (run() is the infinite frameadvance loop). Every collaborator
is a Lua fake that records the order of its calls, so the assertions are about
sequencing: nothing on a quiet frame, persist before drain, heartbeat inventory,
sequence numbers landing in the baseline, writer service only after publication,
pump every tick, and fail-closed batch bounds. The fakes also refuse any call made
outside ctx.at_boundary, which is the relaxed predicate the real sources will use.
"""
import os

import pytest

pytest.importorskip("lupa")
from lupa.lua54 import LuaError, LuaRuntime  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HARNESS = """
package.path=root.."/lua/?.lua;"..package.path
JSON=require("json_codec");Loop=require("gen1_observation_loop")
calls={};appended={};persisted={};prepared_with={}
frame=99;queue=JSON.array();receipts=JSON.array();witness=JSON.array();pending_write=false;inventories=0
battle=0;opponent=0;instruction=nil
local function note(name)
    assert(ctx.at_boundary==true,name.." called outside a frame boundary")
    calls[#calls+1]=name
end
local function clone(v)return assert(JSON.decode(assert(JSON.encode(v))))end
engine={peek=function()note("peek");return clone(queue)end,
    probe=function()assert(ctx.at_boundary==true,"probe called outside a frame boundary");return {battle=battle,opponent=opponent}end,
    drain=function(_,expected)
        note("drain");assert(JSON.encode(expected)==JSON.encode(queue),"drain differs from peek")
        queue=JSON.array();return true
    end,
    batch=function(_,signals,sequence)
        note("batch");return {schema="rby-engine-signals-v1",sequence=sequence,signals=clone(signals)}
    end}
observers={initial=function(_,at)note("initial");return {frame=at,capture_open=JSON.null}end,
    prepare=function(_,state)
        note("prepare");prepared_with[#prepared_with+1]=clone(state)
        assert(frame==state.frame+1,"acquisition assembly requires exactly one returned frame")
        local next_state=clone(state);next_state.frame=frame
        if #witness>0 then next_state.capture_open=clone(witness[1])end
        return {state=next_state,receipts=clone(receipts),capture=clone(witness),grants=JSON.array(),
            static=JSON.array(),npc_exchange=JSON.array(),wild=JSON.array(),evolution=JSON.array()}
    end,
    drain=function(_,rows)note("observers_drain");receipts=JSON.array();witness=JSON.array();return true end,
    ready=function(_,state)note("ready");assert(state.frame==frame,"ready frame differs");return true end}
journal={append=function(_,event,baseline)
        note("append");appended[#appended+1]={event=clone(event),baseline=clone(baseline)}
        return string.rep("a",32)
    end,
    append_many=function(_,events,baseline)
        note("persist");assert(#events==0,"cursor-only persist carries no event")
        persisted[#persisted+1]=clone(baseline);return JSON.array()
    end}
session={pump=function()calls[#calls+1]="pump"end}
writer={pending=function()calls[#calls+1]="pending";return pending_write end,
    service=function()calls[#calls+1]="service"end}
baseline=JSON.object()
function build()
    ctx={engine=engine,observers=observers,journal=journal,session=session,writer=writer,baseline=baseline,instruction=instruction,
        frame=function()return frame end,owned=function()return {context_generation=string.rep("a",32)}end,
        rom_hash=function()return string.rep("f",40)end,
        inventory=function()inventories=inventories+1;return {schema="fixture-inventory",frame=frame}end}
    loop=Loop.new(ctx)
end
function advance(count)for _=1,count or 1 do frame=frame+1;calls={};loop:tick()end end
function signal()queue[#queue+1]={kind="faint",frame=frame+1}end
function receipt()receipts[#receipts+1]={kind="grant",receipt={frame=frame+1}}end
"""


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().root = REPO.replace(os.sep, "/")
    runtime.execute(HARNESS)
    runtime.execute("build()")
    return runtime


def calls(lua):
    return list(lua.globals().calls.values())


def test_quiet_non_heartbeat_frame_publishes_nothing(lua):
    lua.globals().advance()  # frame 100
    assert calls(lua) == ["peek", "prepare", "pending", "pump", "ready"]
    assert lua.eval("#appended") == 0 and lua.eval("#persisted") == 0
    assert lua.eval("prepared_with[1].frame") == 99, "the cursor came from observers:initial at the start frame"
    assert lua.eval("ctx.at_boundary") is False


def test_signals_are_appended_before_the_engine_drains(lua):
    lua.globals().signal()
    lua.globals().advance()
    seq = calls(lua)
    assert seq.index("batch") < seq.index("append") < seq.index("drain") < seq.index("observers_drain")
    assert lua.eval("#appended") == 1 and lua.eval("#queue") == 0
    assert lua.eval("appended[1].event.event") == "observation"
    assert lua.eval("appended[1].event.frame") == 100
    assert lua.eval("#appended[1].event.signals.signals") == 1
    assert lua.eval("appended[1].event.inventory == JSON.null") is True


def test_heartbeat_frame_publishes_inventory_with_nothing_else(lua):
    lua.globals().advance(21)  # 100..119 quiet, then frame 120 = 4 * 30
    seq = calls(lua)
    assert lua.eval("#appended") == 1 and lua.globals().inventories == 1
    assert lua.eval("appended[1].event.inventory.schema") == "fixture-inventory"
    assert lua.eval("appended[1].event.signals == JSON.null") is True
    assert lua.eval("JSON.kind(appended[1].event.acquisitions)") == "array"
    assert lua.eval("#appended[1].event.acquisitions") == 0
    assert "drain" not in seq and seq.index("append") < seq.index("observers_drain")
    lua.globals().advance()  # frame 121: quiet again
    assert lua.eval("#appended") == 1 and lua.globals().inventories == 1


def test_sequence_increments_per_event_and_lands_in_the_baseline(lua):
    lua.globals().signal()
    lua.globals().advance()  # frame 100: signal
    lua.globals().advance(20)  # frame 120: heartbeat
    lua.globals().signal()
    lua.globals().advance()  # frame 121: signal
    assert [lua.eval(f"appended[{i}].event.sequence") for i in (1, 2, 3)] == [1, 2, 3]
    assert [lua.eval(f"appended[{i}].baseline.observation_sequence") for i in (1, 2, 3)] == [1, 2, 3]
    assert lua.eval("baseline.observation_sequence") == 3
    # engine batches keep their own contiguous counter (server/gen1_engine_signal_runtime.py:87)
    assert [lua.eval(f"appended[{i}].event.signals.sequence") for i in (1, 3)] == [1, 2]
    assert lua.eval("baseline.engine_signals.sequence") == 2
    assert lua.eval("appended[3].baseline.acquisition_source.frame") == 121


def test_writer_is_serviced_only_when_pending_and_after_publication(lua):
    lua.globals().advance()
    assert "pending" in calls(lua) and "service" not in calls(lua)
    lua.globals().pending_write = True
    lua.globals().signal()
    lua.globals().advance()
    seq = calls(lua)
    assert seq.index("append") < seq.index("drain") < seq.index("service") < seq.index("pump")


def test_session_is_pumped_every_tick(lua):
    lua.execute("pumps=0;session.pump=function()pumps=pumps+1 end")
    lua.globals().advance(45)  # quiet frames, one heartbeat, back to quiet
    assert lua.globals().pumps == 45 and lua.eval("#appended") == 1


@pytest.mark.parametrize("source,count,message", [
    ("signal", 33, "frame signal batch exceeds source bounds"),
    ("receipt", 17, "frame acquisition batch exceeds source bounds"),
])
def test_oversized_batches_fail_closed_without_dropping(lua, source, count, message):
    lua.execute(f"for _=1,{count} do {source}() end")
    with pytest.raises(LuaError, match=message):
        lua.globals().advance()
    assert lua.eval("#appended") == 0 and "drain" not in calls(lua)
    assert lua.eval("#queue + #receipts") == count, "refused, not dropped"
    assert lua.eval("ctx.at_boundary") is False


def test_capture_call_without_receipt_persists_the_cursor_before_drain(lua):
    lua.execute("""witness[1]={kind="party_begin",frame=frame+1,sp=57342}""")
    lua.globals().advance()
    seq = calls(lua)
    assert "append" not in seq and seq.index("persist") < seq.index("observers_drain")
    assert lua.eval("persisted[1].acquisition_source.capture_open.kind") == "party_begin"
    assert lua.eval("persisted[1].acquisition_source.frame") == 100
    lua.globals().advance()
    assert lua.eval("prepared_with[2].capture_open.kind") == "party_begin", "the next prepare sees the moved cursor"


def test_persisted_cursor_is_adopted_instead_of_a_fresh_initial(lua):
    lua.execute("baseline.acquisition_source={frame=99,capture_open=JSON.null,fixture=true};calls={};build()")
    assert "initial" not in calls(lua)
    lua.globals().advance()
    assert lua.eval("prepared_with[1].fixture") is True


def test_runs_without_acquisition_observers(lua):
    lua.execute("observers=nil;build()")
    lua.globals().signal()
    lua.globals().advance()
    assert lua.eval("#appended") == 1
    assert lua.eval("JSON.kind(appended[1].event.acquisitions)") == "array"
    assert "prepare" not in calls(lua) and "ready" not in calls(lua)


def test_engine_probe_is_required(lua):
    with pytest.raises(LuaError, match="dependencies required"):
        lua.execute("engine.probe=nil;build()")


def test_every_event_carries_the_polled_battle_byte_and_no_trainer_row_by_default(lua):
    lua.globals().signal()
    lua.globals().advance()
    assert lua.eval("appended[1].event.battle") == 0 and lua.eval("appended[1].event.trainer == JSON.null") is True
    lua.execute("battle=1;opponent=36")  # a wild battle: the species id in wCurOpponent, flag 1
    lua.globals().signal()
    lua.globals().advance()
    assert lua.eval("appended[2].event.battle") == 1 and lua.eval("appended[2].event.trainer == JSON.null") is True


def test_trainer_engagement_publishes_once_after_three_stable_ticks(lua):
    lua.execute("battle=2;opponent=225")  # rival class 25 + OPP_ID_OFFSET while wIsInBattle == 2
    lua.globals().advance(2)  # frames 100, 101: not stable yet
    assert lua.eval("#appended") == 0
    lua.globals().advance()  # frame 102: the third stable tick publishes at once, off-heartbeat
    assert lua.eval("#appended") == 1
    assert lua.eval("appended[1].event.trainer.trainer_id") == 225 and lua.eval("appended[1].event.trainer.frame") == 102
    assert lua.eval("appended[1].event.battle") == 2 and lua.eval("appended[1].event.signals == JSON.null") is True
    lua.globals().advance(18)  # through the frame 120 heartbeat: the same engagement is not published again
    assert lua.eval("#appended") == 2 and lua.eval("appended[2].event.trainer == JSON.null") is True
    lua.execute("battle=0;opponent=0")
    lua.globals().advance(5)
    lua.execute("battle=2;opponent=225")
    lua.globals().advance(3)  # the next engagement is a new row
    assert lua.eval("#appended") == 3 and lua.eval("appended[3].event.trainer.trainer_id") == 225


def test_trainer_row_needs_a_trainer_class_the_trainer_flag_and_a_steady_byte(lua):
    lua.execute("battle=1;opponent=225")  # the wild flag never engages
    lua.globals().advance(5)
    lua.execute("battle=2;opponent=36")  # a species id is not a trainer class
    lua.globals().advance(5)
    lua.execute("battle=2;opponent=225")
    lua.globals().advance()
    lua.execute("opponent=226")  # a byte still being written restarts the count
    lua.globals().advance(2)
    assert lua.eval("#appended") == 0
    lua.globals().advance()
    assert lua.eval("#appended") == 1 and lua.eval("appended[1].event.trainer.trainer_id") == 226


def test_instruction_window_finishes_first_and_arms_last_in_a_tick(lua):
    lua.execute("""instruction={finish=function()calls[#calls+1]="finish" end,arm=function()calls[#calls+1]="arm" end};build()""")
    lua.globals().pending_write = True
    lua.globals().signal()
    lua.globals().advance()
    seq = calls(lua)
    assert seq[0] == "finish" and seq[-1] == "arm"
    assert seq.index("append") < seq.index("service") < seq.index("pump") < seq.index("arm")
    lua.execute("frame=frame+1;calls={};loop:observe()")  # a writer that steps frames itself never touches the window
    assert "finish" not in calls(lua) and "arm" not in calls(lua)
