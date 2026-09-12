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
