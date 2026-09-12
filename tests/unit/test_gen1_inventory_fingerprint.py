from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def probe():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        calls={};fault=nil;changed=nil
        local function bytes(address,count,domain)
            local byte=(address+(domain=='CartRAM'and 17 or 31))%256
            if changed==domain..':'..address then byte=(byte+1)%256 end
            return string.rep(string.char(byte),count)
        end
        memory={read_bytes_as_binary_string=function(address,count,domain)
                calls[#calls+1]={address=address,count=count,domain=domain}
                if fault=='error'then error('fixture read failure')end
                local value=bytes(address,count,domain)
                return fault=='short'and value:sub(2)or value
            end}
        mem={PLAYER_ID_ADDR=0xD359,CURRENT_BOX_NUM_ADDR=0xD5A0}
        Fingerprint=require('gen1_inventory_fingerprint')
        first=Fingerprint.capture(mem,'red')
    """)
    return lua


def test_exact_inventory_vector_uses_only_native_bulk_reads_and_all_twelve_boxes(probe):
    assert probe.eval("#calls") == 17
    assert probe.eval("#first.boxes") == 12
    assert probe.eval("#first.fields.party") == 404
    assert probe.eval("#first.fields.box") == 1122
    assert probe.eval("#first.fields.name") == 11
    assert probe.eval("#first.fields.player_id") == 2
    assert probe.eval("#first.fields.current_box") == 1
    assert probe.eval("Fingerprint.same(first,Fingerprint.capture(mem,'red'))") is True


def test_every_byte_of_party_current_box_and_all_twelve_stored_boxes_is_dirty(probe):
    probe.execute("""
        local function changed(field,box,offset)
            local fields={};for name,value in pairs(first.fields)do fields[name]=value end
            local boxes={};for index,value in ipairs(first.boxes)do boxes[index]=value end
            local target=box and boxes[box]or fields[field]
            local replacement=target:sub(1,offset-1)..string.char((target:byte(offset)+1)%256)..target:sub(offset+1)
            if box then boxes[box]=replacement else fields[field]=replacement end
            return {schema=first.schema,variant=first.variant,fields=fields,boxes=boxes}
        end
        for offset=1,#first.fields.party do assert(not Fingerprint.same(first,changed('party',nil,offset)))end
        for offset=1,#first.fields.box do assert(not Fingerprint.same(first,changed('box',nil,offset)))end
        for box=1,12 do
            for offset=1,#first.boxes[box]do assert(not Fingerprint.same(first,changed(nil,box,offset)))end
        end
    """)


@pytest.mark.parametrize("expression", [
    "'System Bus:'..mem.PLAYER_ID_ADDR",
    "'System Bus:'..mem.CURRENT_BOX_NUM_ADDR",
    "'System Bus:'..assert(require('gen1_full_save_layout').red.regions.party.address)",
    "'System Bus:'..assert(require('gen1_full_save_layout').red.regions.box.address)",
    "'System Bus:'..assert(require('gen1_full_save_layout').red.regions.name.address)",
    "'CartRAM:'..(2*0x2000)",
    "'CartRAM:'..(3*0x2000+5*1122)",
])
def test_any_inventory_region_change_marks_the_vector_dirty(probe, expression):
    probe.execute(f"changed={expression};second=Fingerprint.capture(mem,'red')")
    assert probe.eval("Fingerprint.same(first,second)") is False


@pytest.mark.parametrize("fault", ["error", "short"])
def test_bulk_reader_failure_is_fail_closed(probe, fault):
    probe.globals().fault = fault
    with pytest.raises(LuaError):
        probe.eval("Fingerprint.capture(mem,'red')")
