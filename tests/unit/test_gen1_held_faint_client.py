import json

import pytest

from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401


@pytest.mark.parametrize('cmd',['force_faint','force_explode'])
@pytest.mark.parametrize('hp',[0,10])
def test_prepare_and_noop_wait_for_permission_then_complete_without_frames(runtime,hp,cmd):  # noqa: F811
    lua=runtime;start(lua);lua.globals().hp=hp;lua.globals().cmd=cmd
    lua.execute('''
        package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
        package.loaded.platform_identity={new_nonce=new_id}
        now=1;frame=100;physical_writes=0;held=true
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('e',40)end}
        context={context_generation=string.rep('c',32),save_identity={ot_id='0000',trainer_name='SAME'}}
        current={hp=hp};body={cmd=cmd,key='key',death_id=string.rep('d',32)}
        local event=assert(journal:append({event='fixture'}));id=string.rep('a',32)
        assert(journal:accept_response(event,JSON.array({{command_id=id,command_sequence=1,body={cmd=body.cmd,body=body}}})))
        package.loaded.gen1_force_faint_executor={new=function()return {
            prepare=function()return {schema='fixture-intent',before={hp=hp},after={hp=0}}end,
            classify=function()return current.hp==0 and 'after' or 'before',current end,
            apply=function()physical_writes=physical_writes+1;current={hp=0}end,
            receipt=function()return {schema='fixture-receipt',hp=current.hp}end}end}
        package.loaded.gen1_command_receipts={party_snapshot=function()return current end}
        package.loaded.gen1_write_checkpoint={capture=function()return {fixture=true}end}
        service=require('gen1_held_faint').new({journal=journal,memory={profile={},isPartyWriteSafe=function()return true end},
            player='b',variant='yellow',clock=function()return now end,owned=function()return context end,
            host={status=function()return {owner_id=string.rep('b',32),capability_id='fixture',process_id=1,physical_stop_verified=held}end}})
        local adapter={}
        for _,name in ipairs({'prepare','classify','receipt'})do adapter[name]=function(wrapped,...)return service.adapter[name](wrapped.body,...)end end
        adapter.apply=function(wrapped,intent,identity)
            assert(service.operations.authorize_apply(wrapped.body,intent,identity,{admitted=true,held=true}))
            return service.adapter.apply(wrapped.body,intent,identity)
        end
        executor=require('command_executor').new(journal,adapter)
        function step()return executor:step(id)end
        function request()
            local value=service.operations.request({binding_digest=string.rep('f',64)},{admitted=true,held=true})
            return JSON.encode(value)
        end
        function grant()
            local request=JSON.decode(request());local proof=journal.store.backend.sha256(assert(require('journal_document').encode(request.evidence)))
            return service.operations.accept(JSON.object({schema='slink-held-write-permit-v1',scope=request.window.scope,
                challenge=request.window.challenge,uses=1,ttl_ms=1000,proof_digest=proof}))
        end
    ''')
    done,result=lua.globals().step()
    assert done is False and result['pending'] is True and lua.globals().physical_writes==0,dict(result.items())
    requested=json.loads(lua.globals().request())
    assert requested['evidence']['schema']=='rby-held-faint-evidence-v1' and requested['window']['scope']['phase']==cmd
    assert lua.globals().grant()[0] is True
    done,result=lua.globals().step()
    assert done is True and result['outcome']=='ACK' and lua.globals().physical_writes==(0 if hp==0 else 1)
    # The faint executor produced the receipt; force_explode names itself so the server settles that command.
    assert result['receipt']['schema']==('fixture-receipt' if cmd=='force_faint' else 'gen1-force-explode-receipt-v1')
    assert lua.globals().step()[0] is True and lua.globals().physical_writes==(0 if hp==0 else 1)
    assert lua.globals().frame==100


def test_composed_held_faint_executes_force_explode_as_the_overworld_faint_write(runtime):  # noqa: F811
    """The real faint executor and memory module under the composed service: a force_explode body at the
    overworld checkpoint writes exactly the faint's bytes, and the receipt names force_explode, which the
    server accepts for that command only."""
    from server.gen1_command_receipts import verify_force_faint_receipt
    from server.protocol_journal import JournalError
    from tests.unit.test_gen1_command_receipts import IDENTITY, bind_memory, command_for
    lua=runtime;start(lua)
    before=bind_memory(lua,'yellow');g=lua.globals()
    g.bus[g.M.BATTLE_FLAG_ADDR]=0  # bind_memory stages a battle; the held path runs at the overworld checkpoint
    command={**command_for(before,0),'cmd':'force_explode','death_id':'d'*32}
    g.wire_body=json.dumps(command)
    lua.execute('''
        package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
        package.loaded.platform_identity={new_nonce=new_id}
        now=1;frame=100;held=true
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('e',40)end}
        M.isPartyWriteSafe=function()return true end  -- controlled memory; no live checkpoint assertion
        package.loaded.gen1_write_checkpoint={capture=function()return {fixture=true}end}
        context={context_generation=string.rep('c',32),save_identity={ot_id='F00D',trainer_name='ASH'}}
        body=JSON.decode(wire_body);id=string.rep('a',32)
        local event=assert(journal:append({event='fixture'}))
        assert(journal:accept_response(event,JSON.array({{command_id=id,command_sequence=1,body={cmd=body.cmd,body=body}}})))
        service=require('gen1_held_faint').new({journal=journal,memory=M,player='b',variant='yellow',clock=function()return now end,
            owned=function()return context end,
            host={status=function()return {owner_id=string.rep('b',32),capability_id='fixture',process_id=1,physical_stop_verified=held}end}})
        local adapter={}
        for _,name in ipairs({'prepare','classify','receipt'})do adapter[name]=function(wrapped,...)return service.adapter[name](wrapped.body,...)end end
        adapter.apply=function(wrapped,intent,identity)
            assert(service.operations.authorize_apply(wrapped.body,intent,identity,{admitted=true,held=true}))
            return service.adapter.apply(wrapped.body,intent,identity)
        end
        executor=require('command_executor').new(journal,adapter)
        function step()return executor:step(id)end
        function request()
            return JSON.encode(service.operations.request({binding_digest=string.rep('f',64)},{admitted=true,held=true}))
        end
        function grant()
            local value=JSON.decode(request());local proof=journal.store.backend.sha256(assert(require('journal_document').encode(value.evidence)))
            return service.operations.accept(JSON.object({schema='slink-held-write-permit-v1',scope=value.window.scope,
                challenge=value.window.challenge,uses=1,ttl_ms=1000,proof_digest=proof}))
        end
    ''')
    done,result=g.step()
    assert done is False and result['pending'] is True and result['evidence']['schema']=='rby-held-faint-awaiting-permit-v1'
    assert g.physical_writes==0
    requested=json.loads(g.request())
    assert requested['evidence']['schema']=='rby-held-faint-evidence-v1' and requested['window']['scope']['phase']=='force_explode'
    intent=requested['evidence']['intent']
    assert intent['schema']=='gen1-force-faint-intent-v1' and intent['slot']==0 and intent['before']['battle_flag']==0
    assert requested['evidence']['current']==intent['before']
    assert g.grant()[0] is True
    done,result=g.step()
    assert done is True and result['outcome']=='ACK' and g.physical_writes==2  # the two HP bytes, no battle mirror
    receipt=json.loads(g.disk)['document']['payload']['inbox'][0]['receipt']
    assert receipt['schema']=='gen1-force-explode-receipt-v1' and receipt['after']==json.loads(g.readback())
    assert verify_force_faint_receipt(command,receipt,variant='yellow',identity=IDENTITY)['slot']==0
    with pytest.raises(JournalError,match='versioned force-faint receipt'):
        verify_force_faint_receipt({**command,'cmd':'force_faint'},receipt,variant='yellow',identity=IDENTITY)
    assert g.step()[0] is True and g.physical_writes==2 and g.frame==100
