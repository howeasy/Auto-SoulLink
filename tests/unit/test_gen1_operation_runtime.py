"""Actual Lua/Python durable protocol and window codecs; physical checks are fixtures."""
import json
import pytest

from server.gen1_party_codec import PartyCodec
from server.protocol import canonical_json,decode_frame
from tests.unit.test_gen1_execution_authority import verifier
from tests.unit.test_gen1_runtime_client import client
from tests.unit.test_gen1_runtime_server import RuntimeCase

EXTENSION=r'''
    runtime:revoke('replace test runtime before first HELLO')
    local Window=require('execution_window')
    local binding=nil
    local function current_scope()
        local entry=journal:pending_commands()[1]
        if not binding or not entry then return nil end
        local body=Runtime.unwrap(entry.body,options.player)
        if body.cmd~='force_faint'then return nil end
        return {operation_id=entry.command_id,operation_digest=hash_text(JSON.encode({
            command_id=entry.command_id,command_sequence=entry.command_sequence,body=body})),
            context_generation=binding.context_generation,binding_digest=binding.binding_digest,phase=body.cmd}
    end
    window=Window.new({clock=function()return t end,current_scope=current_scope,
        new_nonce=function()nonce=nonce+1;return 'ee'..string.format('%030x',nonce)end,
        verify_grant=function(packet)return packet.proof_digest==hash_text(JSON.encode({schema='explicit-physical-execution-fixture-v1'}))end})
    revocations=0;prepare_count=0;authorization_count=0
    options.operation_execution={
        request=function(value)
            binding=value
            if not current_scope()then return nil end
            return {window=assert(window:challenge()),evidence={schema='explicit-physical-execution-fixture-v1'}}
        end,
        accept=function(packet)
            if packet==nil then window:revoke('no grant');return true end
            return window:accept(packet)
        end,
        authorize_apply=function(body,intent,identity,control)
            authorization_count=authorization_count+1
            assert(body.cmd=='force_faint'and body.body==nil and intent.schema=='physical-before-fixture-v1')
            assert(control.admitted and identity.command_id==current_scope().operation_id)
            return window:ready(),'exact operation window is required'
        end,
        revoke=function(reason)revocations=revocations+1;binding=nil;window:revoke(reason)end,
        status=function()return window:status()end,
    }
    options.operation_ready=function(body)return body.cmd=='force_faint'end
    options.executor_adapter={
        prepare=function()prepare_count=prepare_count+1;return {schema='physical-before-fixture-v1'}end,
        classify=function()
            if applied>0 then return 'after',assert(JSON.decode(receipt_json))end
            return 'before',{schema='physical-before-fixture-v1'}
        end,
        apply=function()applied=applied+1 end,
        receipt=function(_,_,value)return value end,
    }
    if ordinary_fixture then options.reconciliation=function()return {schema='explicit-test-host-proof-v1'}end end
    runtime=assert(Runtime.new(options))
'''


def receipt(case):
    mon=PartyCodec(case.variants["b"]).validate_blob(case.blobs["b"])
    before={"schema":"gen1-party-readback-v1","variant":case.variants["b"],"save_id":"0000","save_name":"SAME",
        "party_count":1,"party":[mon.raw.hex().upper()],"species_list":[mon.species_index,255],
        "battle_flag":0,"active_slot":None,"battle_hp":None}
    after=json.loads(json.dumps(before));raw=bytearray(mon.raw);raw[1:3]=b"\0\0";after["party"]=[raw.hex().upper()]
    return {"schema":"gen1-force-faint-receipt-v1","before":before,"after":after}


@pytest.mark.parametrize("ordinary",[False,True])
def test_configured_operation_policy_defers_apply_until_a_current_server_window(ordinary,tmp_path):
    case=RuntimeCase(tmp_path)
    clients={p:client(case,p) for p in ("a","b")};owners={p:object() for p in clients}
    allow=False;tick=0;responses=[]
    case.runtime.verify_operation_execution=lambda *args:verifier(*args) if allow else None
    for p,lua in clients.items():
        lua.globals().ordinary_fixture=ordinary
        lua.globals().receipt_json=json.dumps(receipt(case))
        lua.execute(EXTENSION)
    def exchange(count):
        nonlocal tick
        for _ in range(count):
            tick+=1;case.time=10+tick*.05
            for p,lua in clients.items():
                g=lua.globals();g.t=tick*.05
                assert g.step() is True
                while (line:=g.pop()) is not None:
                    message=decode_frame(line.encode());response=case.runtime.process(message,owners[p])
                    responses.append(response);g.push(canonical_json(response))
                assert g.frames==0
    try:
        exchange(10)
        clients["a"].globals().observe(json.dumps([{"event":"faint","key":case.keys["a"]}]))
        exchange(20)
        assert clients["b"].globals().applied==0
        assert any(response.get("operation_execution","absent") is None for response in responses)
        if ordinary:assert any(response.get("control",{}).get("authority")=="run" for response in responses)
        pending=case.runtime.journal.pending_ids("b")
        selected=[identifier for identifier in pending if case.runtime.journal.command("b",identifier)["body"]["cmd"]=="force_faint"]
        assert len(selected)==1 and selected[0]==pending[0]
        allow=True;exchange(20)
        assert clients["b"].globals().applied==clients["b"].globals().prepare_count==1
        assert case.runtime.journal.command("b",selected[0])["outcome"]=="ACK"
        assert selected[0] not in case.runtime.journal.pending_ids("b")
        assert any(response.get("operation_execution") for response in responses)
        assert all(lua.globals().revocations>=2 for lua in clients.values())
    finally:case.close()


def test_failed_operation_revocation_keeps_the_host_held(tmp_path):
    case=RuntimeCase(tmp_path)
    try:
        lua=client(case,"b");lua.globals().receipt_json=json.dumps(receipt(case));lua.execute(EXTENSION)
        lua.execute("options.operation_execution.revoke=function()error('injected revoke failure')end;runtime:revoke('test stop')")
        status=json.loads(lua.globals().status_json())
        assert status["failed"] and status["phase"]=="failed" and lua.globals().held is True
        assert lua.globals().applied==0
    finally:case.close()
