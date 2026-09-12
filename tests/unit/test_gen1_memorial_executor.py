"""Actual prepared executor and permits, real Lua memory codec, modeled host/file."""

import hashlib
import json

import pytest
from lupa.lua54 import LuaError

from server.gen1_full_save import layout
from server.gen1_memorial import expected
from server.gen1_memorial_runtime import wire_payload
from tests.unit.test_gen1_memorial import fixture, load_point
from tests.unit.test_gen1_party_codec import ROOT


def client(variant, fail_after=None, foreign=False):
    before, key, identity = fixture(variant, count=3, slot=0)
    after = expected(before, key, identity=identity)
    payload = {
        "before": before,
        "after": after,
        "context_generation": "c" * 32,
        "final_sha1": "f" * 40,
        "frame": 100,
    }
    body = {
        "cmd": "memorialize",
        "death_id": "d" * 32,
        "key": key,
        "payload": wire_payload(payload),
    }
    lua, mem = load_point(before)
    lua.globals().root = ROOT.as_posix()
    lua.globals().mem = mem
    lua.globals().hash_text = lambda text: hashlib.sha256(text.encode()).hexdigest()
    lua.globals().command_json = json.dumps(body)
    lua.globals().save_json = json.dumps(identity)
    lua.globals().fail_after = -1 if fail_after is None else fail_after
    lua.globals().foreign = foreign
    lua.globals().bus[layout(variant)["status"]] = before["save_status"]
    lua.globals().variant = variant
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Canonical=require('journal_document');Full=require('gen1_full_save')
        local Journal=require('client_journal');local Store=require('state_store')
        disk=nil;writes=0;file_writes=0;now=1;failed_once=false;held=true
        backend={sha256=function(text)return hash_text(text)end,read=function()if disk then return disk end;return nil,'missing'end,
            replace=function(text)disk=text;return true end,close=function()end}
        store=assert(Store.open(backend,{fixture=true},Journal.initial()));local nonce=0
        function new_id()nonce=nonce+1;return string.format('%032x',nonce)end
        journal=assert(Journal.open(store,new_id));local command=assert(JSON.decode(command_json))
        local origin=assert(journal:append({event='fixture'}));id=string.rep('a',32)
        assert(journal:accept_response(origin,JSON.array({{command_id=id,command_sequence=1,body={cmd=command.cmd,body=command}}})))
        emu={framecount=function()return 100 end};gameinfo={getromhash=function()return string.rep('f',40)end}
        mem.isPartyWriteSafe=function()return held end
        package.loaded.gen1_write_checkpoint={capture=function()return {fixture=true}end}
        package.loaded.platform_identity={new_nonce=new_id}
        package.loaded.platform_saveram={new=function(options)
            assert(options.authorize())
            return {flush=function(_,hex)
                assert(options.authorize());file_writes=file_writes+1
                return {schema='slink-saveram-file-v1',path='fixture.sav',sha256='fixture',byte_length=#hex/2,
                    frame=100,host_profile='fixture',flushed=true,readback=true}
            end}
        end}
        local original_write=memory.write_u8
        memory.write_u8=function(address,value,domain)
            if writes==fail_after and not failed_once then
                failed_once=true
                if foreign then original_write(10,77,'CartRAM')end
                error('injected partial write')
            end
            original_write(address,value,domain)
        end
        service=require('gen1_held_faint').new({journal=journal,memory=mem,variant=variant,player='a',clock=function()return now end,
            owned=function()return {context_generation=string.rep('c',32),save_identity=JSON.decode(save_json)}end,
            host={status=function()return {owner_id=string.rep('a',32),capability_id='fixture',process_id=1,physical_stop_verified=held}end}})
        local adapter={}
        for _,name in ipairs({'prepare','classify','receipt'})do adapter[name]=function(body,...)return service.adapter[name](body.body,...)end end
        adapter.apply=function(body,intent,identity)
            assert(service.operations.authorize_apply(body.body,intent,identity,{admitted=true,held=true}))
            return service.adapter.apply(body.body,intent,identity)
        end
        executor=require('command_executor').new(journal,adapter)
        function step()return executor:step(id)end
        function grant()
            local request=assert(service.operations.request({binding_digest=string.rep('b',64)},{admitted=true,held=true}))
            local packet={schema='slink-held-write-permit-v1',challenge=request.window.challenge,scope=request.window.scope,
                uses=1,ttl_ms=1000,proof_digest=hash_text(assert(Canonical.encode(request.evidence)))}
            assert(service.operations.accept(JSON.object(packet)));return packet.scope.phase
        end
        function point_json()return assert(JSON.encode(Full.capture(mem,variant)))end
    """)
    return lua, before, after


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("fail_after", [None, 0, 1, 20, 80, 140])
def test_explained_partial_writes_require_fresh_permission_and_finish_exactly_once(
    variant, fail_after
):
    lua, before, after = client(variant, fail_after)
    g = lua.globals()
    assert g.step()[0] is False and g.writes == 0 and g.file_writes == 0
    phases = []
    for _ in range(5):
        phases.append(g.grant())
        done, result = g.step()
        if done:
            break
        assert result["pending"] is True
    assert done and result["outcome"] == "ACK"
    assert json.loads(g.point_json()) == after and g.file_writes == 1
    count = g.writes
    assert g.step()[0] is True and g.writes == count and g.file_writes == 1
    assert phases[-1] == "memorial_save"
    if fail_after is not None and fail_after > 0 and g.failed_once:
        assert "memorial_repair" in phases


def test_foreign_byte_during_failure_never_becomes_repair_permission():
    lua, _, _ = client("yellow", 1, foreign=True)
    g = lua.globals()
    g.step()
    g.grant()
    done, result = g.step()
    assert not done and result["outcome"] == "NACK" and not result["pending"]
    assert g.file_writes == 0
    with pytest.raises(LuaError):
        g.grant()


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("where", ["cart_outside_delta", "unchanged_wram"])
def test_apply_rechecks_complete_preimage_before_any_memory_or_file_write(variant, where):
    lua, _, _ = client(variant)
    g = lua.globals()
    lua.execute("""
        prepared_body=assert(JSON.decode(command_json))
        writer=require('gen1_held_memorial').new({memory=mem,variant=variant,
            safe=function()return true end,permitted=function()return true end,
            owned=function()return {context_generation=string.rep('c',32)}end,
            sha=function(value)return hash_text(assert(Canonical.encode(value)))end})
        prepared_intent=writer.prepare(prepared_body)
    """)
    assert g.writes == 0 and g.file_writes == 0
    if where == "cart_outside_delta":
        g.cart[10] = (g.cart[10] + 1) % 256
    else:
        address = layout(variant)["regions"]["name"]["address"]
        g.bus[address] = (g.bus[address] + 1) % 256
    # Call apply itself: no classify/ready guard may hide a missing write-time check.
    with pytest.raises(LuaError, match="foreign data"):
        lua.execute("writer.apply(prepared_body,prepared_intent)")
    assert g.writes == 0 and g.file_writes == 0
