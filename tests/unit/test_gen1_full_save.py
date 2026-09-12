import json
import random
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server.gen1_full_save import image, layout
from server.protocol_journal import JournalError
from tools.gen_gen1_full_save_layout import TARGET, generated

ROOT=Path(__file__).resolve().parents[2]


def point(variant, seed=12):
    rng=random.Random(seed)
    return {'schema':'rby-full-save-point-v1','variant':variant,'save_status':1,
            'cart_hex':rng.randbytes(0x8000).hex().upper(),
            'fields':{name:rng.randbytes(region['length']).hex().upper() for name,region in layout(variant)['regions'].items()}}


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_full_save_preserves_every_byte_outside_source_defined_save_data(variant):
    observed=point(variant);info=layout(variant);before=bytes.fromhex(observed['cart_hex']);after=image(observed)
    assert after[:info['start']]==before[:info['start']]
    assert after[info['checksum']+1:]==before[info['checksum']+1:]
    assert sum(after[info['start']:info['checksum']+1])%256==255
    for name,region in info['regions'].items():
        assert after[region['target']:region['target']+region['length']]==bytes.fromhex(observed['fields'][name])


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_actual_lua_copy_plan_matches_python_for_complete_images(variant):
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=ROOT.as_posix()
    lua.execute('''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Full=require('gen1_full_save')
        mem={hexToBytes=function(text)local out={};for i=1,#text,2 do out[#out+1]=tonumber(text:sub(i,i+1),16)end;return out end,
             bytesToHex=function(values)local out={};for _,value in ipairs(values)do out[#out+1]=string.format('%02X',value)end;return table.concat(out)end}
        function build(text)return Full.image(mem,assert(JSON.decode(text)))end
    ''')
    for seed in (0,1,22,99):
        observed=point(variant,seed)
        assert lua.globals().build(json.dumps(observed))==image(observed).hex().upper()


@pytest.mark.parametrize('fault',['missing','extra','short','status','variant'])
def test_incomplete_save_sources_are_refused(fault):
    observed=point('yellow')
    if fault=='missing':del observed['fields']['sprites']
    elif fault=='extra':observed['fields']['other']='00'
    elif fault=='short':observed['fields']['box']=observed['fields']['box'][:-2]
    elif fault=='status':observed['save_status']=True
    else:observed['variant']='crystal'
    with pytest.raises(JournalError):image(observed)


def test_lua_layout_matches_the_current_pinned_symbol_generation():
    assert TARGET.read_text()==generated()


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_bulk_and_scalar_capture_are_byte_identical_and_domain_explicit(variant):
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=ROOT.as_posix();lua.globals().variant=variant
    lua.execute('''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec')
        scalar_calls=0;bulk_calls={};frame=123
        local function byte(address,domain)return (address+(domain=='CartRAM'and 37 or 11))%256 end
        memory={read_u8=function(address,domain)scalar_calls=scalar_calls+1;return byte(address,domain)end}
        mem={bytesToHex=function(values)local out={};for _,value in ipairs(values)do out[#out+1]=string.format('%02X',value)end;return table.concat(out)end}
        Full=require('gen1_full_save')
        scalar=assert(JSON.encode(Full.capture(mem,variant)))
        scalar_count=scalar_calls;scalar_calls=0
        memory.read_bytes_as_array=function(address,count,domain)
            bulk_calls[#bulk_calls+1]={address=address,count=count,domain=domain}
            local out={};for i=0,count-1 do out[i+1]=byte(address+i,domain)end;return out
        end
        bulk=assert(JSON.encode(Full.capture(mem,variant)))
    ''')
    assert json.loads(lua.globals().bulk)==json.loads(lua.globals().scalar)
    assert lua.globals().scalar_count==0x8000+sum(row['length'] for row in layout(variant)['regions'].values())+1
    calls=list(lua.globals().bulk_calls.values())
    assert len(calls)==7 and sum(row['count'] for row in calls)==0x8000+sum(
        region['length'] for region in layout(variant)['regions'].values())
    assert [row['domain'] for row in calls].count('CartRAM')==1
    assert all(row['domain'] in ('System Bus','CartRAM') for row in calls)
    assert lua.globals().scalar_calls==1,"only the one-byte save status stays scalar"
    assert lua.globals().frame==123


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_native_binary_capture_is_exact_and_preferred_over_array(variant):
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=ROOT.as_posix();lua.globals().variant=variant
    lua.execute('''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Full=require('gen1_full_save')
        local function byte(address,domain)return (address+(domain=='CartRAM'and 37 or 11))%256 end
        memory={read_u8=function(address,domain)return byte(address,domain)end,
            read_bytes_as_array=function(address,count,domain)
                local out={};for i=0,count-1 do out[i+1]=byte(address+i,domain)end;return out
            end}
        array=assert(JSON.encode(Full.capture({},variant)))
        binary_calls=0
        memory.read_bytes_as_array=function()error('binary reader must take precedence')end
        memory.read_bytes_as_binary_string=function(address,count,domain)
            binary_calls=binary_calls+1;local out={}
            for i=0,count-1 do out[i+1]=string.char(byte(address+i,domain))end
            return table.concat(out)
        end
        binary=assert(JSON.encode(Full.capture({},variant)))
    ''')
    assert json.loads(lua.globals().binary)==json.loads(lua.globals().array)
    assert lua.globals().binary_calls==7


def test_callable_userdata_bulk_reader_is_used_instead_of_scalar_fallback():
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=ROOT.as_posix()
    calls=[]
    def native(address,count,domain):
        calls.append((address,count,domain))
        return '\x01'*count
    lua.globals().native=native
    lua.execute('''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        assert(type(native)=='userdata')
        memory={read_bytes_as_binary_string=native,read_bytes_as_array=function()
            error('array fallback forbidden')end,read_u8=function()return 2 end}
        local point=require('gen1_full_save').capture({},'yellow')
        assert(point.cart_hex==string.rep('01',0x8000))
    ''')
    assert len(calls)==7 and sum(count for _,count,_ in calls)==0x8000+sum(
        region['length'] for region in layout('yellow')['regions'].values())


@pytest.mark.parametrize('fault',['error','short','non_byte'])
def test_present_but_invalid_bulk_reader_fails_closed_without_scalar_fallback(fault):
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=ROOT.as_posix();lua.globals().fault=fault
    lua.execute('''
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        scalar_calls=0
        memory={read_u8=function()scalar_calls=scalar_calls+1;return 0 end,
            read_bytes_as_array=function(address,count,domain)
                if fault=='error'then error('fixture bulk failure')end
                local n=fault=='short'and count-1 or count;local out={}
                for i=1,n do out[i]=fault=='non_byte'and i==1 and 256 or 0 end
                return out
            end}
        mem={bytesToHex=function()error('bulk capture must not use the scalar formatter')end}
        Full=require('gen1_full_save')
        ok,why=pcall(Full.capture,mem,'yellow')
    ''')
    assert lua.globals().ok is False and lua.globals().why
    assert lua.globals().scalar_calls==0
