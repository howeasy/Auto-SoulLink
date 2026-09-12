import json
import pytest
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import start


@pytest.mark.parametrize('hp',[0,10])
def test_prepare_and_noop_wait_for_permission_then_complete_without_frames(runtime,hp):  # noqa: F811
    lua=runtime;start(lua);lua.globals().hp=hp
    lua.execute('''
        package.path=root..'/data/games/gen1_rby/?.lua;'..package.path
        package.loaded.platform_identity={new_nonce=new_id}
        now=1;frame=100;physical_writes=0;held=true
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('e',40)end}
        context={context_generation=string.rep('c',32),save_identity={ot_id='0000',trainer_name='SAME'}}
        current={hp=hp};body={cmd='force_faint',key='key',death_id=string.rep('d',32)}
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
    assert lua.globals().grant()[0] is True
    done,result=lua.globals().step()
    assert done is True and result['outcome']=='ACK' and lua.globals().physical_writes==(0 if hp==0 else 1)
    assert lua.globals().step()[0] is True and lua.globals().physical_writes==(0 if hp==0 else 1)
    assert lua.globals().frame==100
