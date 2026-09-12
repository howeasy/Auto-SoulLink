import json
import pytest
from lupa.lua54 import LuaRuntime
from pathlib import Path
from server.held_write_permit import VerifiedHeldWrite, issue, SCHEMA

SCOPE={'operation_id':'a'*32,'operation_digest':'b'*64,'context_generation':'c'*32,'binding_digest':'d'*64,'phase':'force_faint'}


def instance():
    lua=LuaRuntime(unpack_returned_tuples=True);lua.globals().root=Path(__file__).resolve().parents[2].as_posix()
    lua.globals().scope_json=json.dumps(SCOPE)
    lua.execute('''package.path=root..'/lua/?.lua;'..package.path
        JSON=require('json_codec');P=require('held_write_permit');time=1;current=JSON.decode(scope_json);calls=0
        permit=P.new({clock=function()return time end,current_scope=function()
                if delay_scope then time=time+2 end
                if revoke_scope then permit:revoke()end
                return current end,
            new_nonce=function()calls=calls+1;return string.format('%032x',calls)end,
            verify_grant=function(packet)return packet.proof_digest==string.rep('e',64)end})
        function request()return JSON.encode(permit:challenge())end
        function accept(text)return permit:accept(JSON.decode(text))end''')
    return lua


def test_permission_is_single_use_and_never_exposes_frame_credit():
    lua=instance();request=json.loads(lua.globals().request())
    packet=issue(request,VerifiedHeldWrite(SCOPE,'e'*64,1000,'f'*64))
    assert 'frames' not in packet and packet['uses']==1 and packet['schema']==SCHEMA
    assert lua.globals().accept(json.dumps(packet)) is True
    permit=lua.globals().permit
    assert permit.consume(permit) is True and permit.consume(permit) is False
    assert permit.valid(permit) is True
    lua.globals().time=2
    assert permit.valid(permit) is False


@pytest.mark.parametrize('fault',['scope','proof','frames','expired','uses','replay'])
def test_invalid_or_replayed_permission_cannot_be_consumed(fault):
    lua=instance();request=json.loads(lua.globals().request());packet=issue(request,VerifiedHeldWrite(SCOPE,'e'*64,1000,'f'*64))
    if fault=='scope':packet['scope']['operation_id']='f'*32
    elif fault=='proof':packet['proof_digest']='f'*64
    elif fault=='frames':packet['frames']=1
    elif fault=='uses':packet['uses']=2
    elif fault=='expired':lua.globals().time=2
    else:assert lua.globals().accept(json.dumps(packet)) is True
    assert lua.globals().accept(json.dumps(packet))[0] is False
    assert lua.globals().permit.consume(lua.globals().permit)[0] is False


def test_context_change_or_clock_rollback_refuses_use():
    for fault in ('context','clock'):
        lua=instance();packet=issue(json.loads(lua.globals().request()),VerifiedHeldWrite(SCOPE,'e'*64,1000,'f'*64))
        assert lua.globals().accept(json.dumps(packet)) is True
        if fault=='context':lua.execute("current.context_generation=string.rep('f',32)")
        else:lua.globals().time=0
        result=lua.globals().permit.consume(lua.globals().permit)
        assert (result[0] if isinstance(result,tuple) else result) is False


@pytest.mark.parametrize('fault',['delay_scope','revoke_scope'])
def test_scope_callback_cannot_extend_or_restore_permission(fault):
    for phase in ('accept','consume'):
        lua=instance();packet=issue(json.loads(lua.globals().request()),VerifiedHeldWrite(SCOPE,'e'*64,1000,'f'*64))
        if phase=='consume':assert lua.globals().accept(json.dumps(packet)) is True
        lua.globals()[fault]=True
        result=lua.globals().accept(json.dumps(packet)) if phase=='accept' else lua.globals().permit.consume(lua.globals().permit)
        assert (result[0] if isinstance(result,tuple) else result) is False
