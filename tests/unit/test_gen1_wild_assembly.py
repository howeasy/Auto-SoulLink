"""Replay of the first live wild encounter (receipt .cache/d1-rb-parcel-r2-summary.json, player b).

The real free-running loop (lua/gen1_observation_loop.lua) drives the real assembly
(lua/gen1_acquisition_observers.lua) with fake sources. The one host fact modelled is the
pinned bus-exec hook convention (docs/gen1_reference/BATTLE_FORCE_FAINT_WINDOW.md section 10,
HOOK_FRAME_OFFSET = 0): inside a hook `emu.framecount()` still reads the count the frame was
armed at, so a witness stamped during the returned step carries `state.frame`, not the count
the tick reads after `emu.frameadvance()`. Every live engine signal shows the same pairing
(starter_begin 7969 inside observation frame 7970, battle_faint 18761 inside 18762).
"""
import os

import pytest

pytest.importorskip("lupa")
from lupa.lua54 import LuaError, LuaRuntime  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HARNESS = """
package.path=root.."/lua/?.lua;"..root.."/data/games/gen1_rby/?.lua;"..package.path
JSON=require("json_codec");Loop=require("gen1_observation_loop");Acquisitions=require("gen1_acquisition_observers")
frame=3502 -- the held count the loop was constructed at (initial_inventory.frame of the live receipt)
emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep("b",40)end}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function idle()
    return {status=function()return {pending=0,in_flight=0}end,peek=function()return JSON.array()end,
        acknowledge=function(expected)assert(#expected==0);return true end,close=function()end}
end
wild_pending=JSON.array();drained=0
wild={status=function()return {pending=#wild_pending}end,peek=function()return copy(wild_pending)end,
    acknowledge=function(expected)
        assert(JSON.encode(expected)==JSON.encode(wild_pending),"wild receipts changed before durable acknowledgement")
        drained=drained+1;wild_pending=JSON.array();return true
    end,close=function()end}
context={context_generation=string.rep("a",32),physical_instance=string.rep("1",32)}
ctx={at_boundary=false}
observers=Acquisitions.new({variant="blue",final_sha1=string.rep("b",40),owned=function()return context end,fast_path=true,
    held=function()return ctx.at_boundary==true end,capture=idle(),grants=idle(),static=idle(),npc_exchange=idle(),wild=wild,
    evolution=idle(),new_nonce=function()return string.rep("9",32)end})
appended={};battle=0
ctx.engine={peek=function()return JSON.array()end,probe=function()return {battle=battle,opponent=0}end,
    drain=function()return true end,batch=function()error("no engine signals in this replay")end}
ctx.observers=observers
ctx.journal={append=function(_,event,baseline)
        appended[#appended+1]={event=copy(event),baseline=copy(baseline)};return string.rep("a",32)
    end,
    append_many=function()return JSON.array()end}
ctx.session={pump=function()end};ctx.baseline=JSON.object();ctx.owned=function()return context end
ctx.rom_hash=function()return string.rep("b",40)end
loop=Loop.new(ctx)
-- A bus-exec hook fires inside emulation: emu.framecount() is the armed count (HOOK_FRAME_OFFSET = 0).
function hook_wild(kind,at)
    wild_pending[#wild_pending+1]={schema="rby-wild-encounter-receipt-v1",kind=kind,
        witness={frame=at or emu.framecount(),pc=28560,bank=15,sp=57333,point={battle_flag=1}}}
end
function advance(count)for _=1,count or 1 do frame=frame+1;loop:tick()end end
"""


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().root = REPO.replace(os.sep, "/")
    runtime.execute(HARNESS)
    return runtime


def test_wild_begin_witnessed_inside_the_returned_frame_assembles_in_that_step(lua):
    lua.globals().advance(5)  # quiet fast-path frames: 3503..3507
    assert lua.eval("#appended") == 0 and lua.eval("observers:status().wild.pending") == 0
    lua.execute("hook_wild('begin');battle=1")  # InitWildBattle+5 fires during frame 3508, reads 3507
    assert lua.eval("wild_pending[1].witness.frame") == 3507
    lua.globals().advance()  # the tick after that frame reads 3508
    assert lua.eval("#appended") == 1 and lua.globals().drained == 1
    assert lua.eval("appended[1].event.frame") == 3508
    assert lua.eval("appended[1].event.acquisitions[1].kind") == "wild_begin"
    assert lua.eval("appended[1].event.acquisitions[1].receipt.witness.frame") == 3507
    assert lua.eval("appended[1].baseline.acquisition_source.frame") == 3508
    lua.globals().advance()  # quiet again: the cursor kept up
    assert lua.eval("#appended") == 1


def test_wild_end_lands_in_its_own_step_after_a_long_quiet_run(lua):
    lua.execute("hook_wild('begin')")
    lua.globals().advance()
    lua.globals().advance(40)  # 3504..3543: only empty heartbeats (30-frame period, no checkpoint source)
    assert lua.eval("loop:status().acquisition_publications") == 1
    lua.execute("hook_wild('end')")
    lua.globals().advance()
    assert lua.eval("loop:status().acquisition_publications") == 2 and lua.globals().drained == 2
    assert lua.eval("appended[#appended].event.acquisitions[1].kind") == "wild_end"
    assert lua.eval("appended[#appended].event.acquisitions[1].receipt.witness.frame") == 3543
    assert lua.eval("appended[#appended].event.frame") == 3544


@pytest.mark.parametrize("offset", [1, -1])
def test_a_witness_no_hook_could_have_stamped_still_refuses_assembly(lua, offset):
    lua.globals().advance(2)
    lua.execute(f"hook_wild('begin',emu.framecount()+({offset}))")  # the tick's own count, or a frame before the step
    with pytest.raises(LuaError, match="wild_begin completion lies outside returned physical step"):
        lua.globals().advance()
    assert lua.eval("#appended") == 0 and lua.globals().drained == 0
