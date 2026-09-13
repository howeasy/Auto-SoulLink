"""Coherent capture through real full/fingerprint/party readers, with held memory adapters."""
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.gen1_party_codec import PartyCodec
from tests.unit.test_gen1_party_codec import make_blob

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["red", "blue", "yellow"])
def capture(request):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().variant = request.param
    lua.globals().blob = lua.table_from(list(make_blob(PartyCodec(request.param))))
    lua.execute(r'''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');frame=120;held=false;safe=true;calls={};votes={};party_reads=0
        bus={};cart={};fault=nil;drift=nil;party_count=1
        local layout=require('gen1_full_save_layout')[variant]
        local start=layout.regions.party.address
        bus[start]=1;bus[start+1]=blob[1];bus[start+2]=255
        for i=1,44 do bus[start+7+i]=blob[i]end
        for i=1,11 do bus[start+271+i]=blob[44+i];bus[start+337+i]=blob[55+i]end
        local function read(a,d)local domain=d=='CartRAM'and cart or bus;return domain[a]or 0 end
        memory={read_u8=function(a,d)assert(held);return read(a,d)end,
            read_bytes_as_binary_string=function(a,n,d)
                assert(held,'unheld memory read');calls[#calls+1]={address=a,count=n,domain=d}
                if fault=='bulk'then error('bulk fixture failure')end
                if drift=='read'then frame=frame+1 end
                local bytes={};for i=0,n-1 do bytes[#bytes+1]=string.char(read(a+i,d))end
                return table.concat(bytes)
            end}
        mem={PLAYER_ID_ADDR=1,CURRENT_BOX_NUM_ADDR=3,PARTY_SPECIES_ADDR=start+1,BATTLE_FLAG_ADDR=4,
            isPartyWriteSafe=function()return safe end,
            getPartyCount=function()assert(held);party_reads=party_reads+1
                if fault=='party'then error('party fixture failure')end;return party_count end,
            readPartyBlob=function()assert(held);return blob end,
            read_u8=function(a)assert(held);return read(a,'System Bus')end,
            readPlayerId=function()assert(held);return 0x1234 end,
            readPlayerName=function()assert(held);return 'ASH'end,
            bytesToHex=function(bytes)local out={};for i,v in ipairs(bytes)do out[i]=string.format('%02X',v)end;return table.concat(out)end}
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('f',40)end}
        host={status=function()return {physical_stop_verified=held,owner_id=string.rep('b',32),capability_id='fixture',process_id=7}end}
        holds={set=function(_,owner,value,reason)
            assert(owner=='writer');held=value;votes[#votes+1]={held=value,reason=reason}
            if not value and drift=='release'then frame=frame+1 end
            return true
        end}
        function owned()
            assert(held,'owner requires hold');if fault=='owned'then error('owner fixture failure')end
            return {context_generation=string.rep('a',32)}
        end
        function build(native)
            checkpoint=require('gen1_inventory_checkpoint').new({memory=mem,variant=variant,host=host,holds=holds,
                owned=owned,source_owned=owned,frame=function()return frame end,native=native})
        end
        build(true)
    ''')
    return lua


def test_full_capture_pairs_real_party_bytes_and_preserves_inventory_first_return(capture):
    capture.execute("point,native=checkpoint:inventory(frame)")
    capture.execute(r'''
        assert(point.schema=='rby-initial-observation-v1'and point.frame==120)
        assert(point.source.schema=='rby-full-save-point-v1'and #point.source.cart_hex==65536)
        assert(native.schema=='rby-native-observation-v1'and native.party.party_count==1)
        local party=point.source.fields.party
        assert(native.party.party[1]==party:sub(17,104)..party:sub(545,566)..party:sub(677,698))
        assert(not held and #votes==2 and votes[1].held and not votes[2].held and party_reads==1)
        assert(#calls==7) -- six full-save regions + CartRAM, no fingerprint reads
    ''')


def test_seed_quiet_dirty_and_forced_retry_use_only_required_reads(capture):
    capture.execute(r'''
        point,previous,dirty,native=checkpoint:checkpoint(false,true,frame)
        assert(point==nil and dirty==false and native==nil and party_reads==0 and #calls==17)
        point,current,dirty,native=checkpoint:checkpoint(previous,false,frame)
        assert(point==nil and dirty==false and native==nil and party_reads==0 and #calls==34)
        point,current,dirty,native=checkpoint:checkpoint(previous,true,frame)
        assert(point and dirty==true and native.party.party_count==1 and party_reads==1 and #calls==58)
        cart[0x4000]=1
        point,current,dirty,native=checkpoint:checkpoint(previous,false,frame)
        assert(point and dirty==true and native and party_reads==2 and #calls==82)
        assert(not held and #votes==8)
    ''')


def test_unsafe_capture_preserves_previous_without_any_hold_or_memory_read(capture):
    capture.execute(r'''
        safe=false;local previous={opaque=true}
        local point,current,dirty,native=checkpoint:checkpoint(previous,true,frame)
        assert(point==nil and current==previous and dirty==false and native==nil)
        point,native=checkpoint:inventory(frame)
        assert(point==nil and native==nil and #calls==0 and #votes==0 and party_reads==0)
    ''')


def test_native_absent_omits_field_and_enabled_empty_party_returns_json_null(capture):
    capture.execute(r'''
        build(false);local point,native=checkpoint:inventory(frame)
        assert(point and native==nil and party_reads==0)
        build(true);party_count=0;point,native=checkpoint:inventory(frame)
        assert(point and native==JSON.null and party_reads==1)
    ''')


@pytest.mark.parametrize("method", ["inventory(frame-1)", "checkpoint(nil,true,frame-1)",
                                    "inventory(frame)", "checkpoint(nil,true,frame)"])
def test_stale_native_frame_is_refused_without_losing_the_full_point(capture, method):
    if "frame-1" not in method:
        capture.execute("drift='release'")
    capture.execute(f"result=table.pack(checkpoint:{method})")
    capture.execute("assert(result[1].frame==120 and result[result.n]==JSON.null and not held)")


@pytest.mark.parametrize("method", ["inventory(frame)", "checkpoint(nil,true,frame)"])
@pytest.mark.parametrize("fault", ["bulk", "party", "owned", "frame"])
def test_capture_errors_release_writer_hold_before_raising(capture, method, fault):
    capture.execute("drift='read'" if fault == "frame" else f"fault='{fault}'")
    with pytest.raises(LuaError):
        capture.execute(f"checkpoint:{method}")
    capture.execute("assert(not held and #votes==2 and votes[1].held and not votes[2].held)")


def test_real_capture_and_loop_publish_native_only_with_changed_or_forced_inventory(capture):
    capture.execute(r'''
        frame=119;appended={};baseline={};retry=nil
        local ctx={engine={peek=function()return {}end,probe=function()return {battle=0,opponent=0}end},
            journal={append=function(_,event)appended[#appended+1]=event;return true end},session={pump=function()end},
            baseline=baseline,owned=function()return {context_generation=string.rep('a',32)}end,
            rom_hash=function()return gameinfo.getromhash()end,frame=function()return frame end,
            pending_inventory_retry=function()return retry end,
            checkpoint=function(...)return checkpoint:checkpoint(...)end}
        local loop=require('gen1_observation_loop').new(ctx)
        assert(#calls==17 and party_reads==0)
        frame=120;loop:tick();assert(#appended==0 and #calls==34 and party_reads==0)
        retry={};frame=150;loop:tick()
        assert(#appended==1 and appended[1].frame==150 and appended[1].inventory.frame==150)
        assert(appended[1].native_checkpoint.party.party_count==1 and party_reads==1)
        frame=151;loop:tick();assert(#calls==58 and party_reads==1 and #appended==1)
        retry=nil;cart[0x4000]=1;frame=180;loop:tick()
        assert(#appended==2 and appended[2].native_checkpoint.party.party_count==1 and party_reads==2)
    ''')
