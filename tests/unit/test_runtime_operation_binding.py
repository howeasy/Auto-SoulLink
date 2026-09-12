"""Optional operation callbacks cannot bypass the shared deadline/context guards."""
import pytest

from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime as runtime


@pytest.mark.parametrize('mode',['default','deny','allow','late','context','revoke','operation_false'])
def test_optional_operation_binding_and_default_are_explicit_and_rechecked(runtime,mode):
    lua=runtime
    start(lua)
    lua.globals().mode=mode
    lua.execute('''
        local Runtime=require('durable_runtime')
        now=0;connected=false;incoming={};applied=0;granted=false;held=true;revocations=0;authorizations=0
        context=string.rep('3',32)
        local binding={session_id=string.rep('1',32),admission_epoch=string.rep('2',32),
            context_generation=context,binding_digest=string.rep('4',64)}
        local issued=false
        local transport={init=function()connected=true end,connected=function()return connected end,pump=function()end,
            disconnect=function()connected=false;incoming={}end,receive=function()return table.remove(incoming,1)end,
            queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,
                receive_bytes=0,partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
            send=function(raw)
                local packet=assert(JSON.decode(raw))
                local response={protocol=packet.protocol,player=packet.player,seq=packet.seq,operation_id=packet.operation_id,
                    session_id=binding.session_id,admission_epoch=binding.admission_epoch,ack='ACK',commands=JSON.array()}
                if packet.event=='hello'then response.admission={state='admitted',client_nonce=packet.client_nonce,control_binding=binding}
                elseif packet.event=='control'then
                    response.recovery=JSON.object()
                    response.control={session_id=binding.session_id,admission_epoch=binding.admission_epoch,
                        context_generation=binding.context_generation,binding_digest=binding.binding_digest,
                        challenge=packet.control.challenge,authority='hold',reason='test held owner'}
                    if mode~='default' then response.operation_execution=JSON.object({fixture=true})end
                elseif not issued then
                    local command={cmd='fixture',command_id=string.rep('5',32),command_sequence=1,command_index=1}
                    for _,key in ipairs({'protocol','player','seq','operation_id','session_id','admission_epoch'})do command[key]=response[key]end
                    response.commands=JSON.array({command});issued=true
                end
                incoming[#incoming+1]=assert(JSON.encode(response));return true
            end}
        local options={protocol='fixture-runtime-v1',hold_event='fixture_hold',player='a',journal=journal,
            clock=function()return now end,transport=transport,server_host='localhost',server_port=1,
            read_hello=function()return {context_generation=context}end,metadata_matches=function()return true end,
            new_nonce=new_id,host={set_held=function(value)held=value;return true end},operation_ready=function()return true end,
            executor_adapter={prepare=function()return {schema='fixture-intent'}end,
                classify=function()return applied==1 and 'after' or 'before',{applied=applied}end,
                apply=function()applied=applied+1 end,receipt=function()return {schema='fixture-receipt',applied=applied}end}}
        if mode=='operation_false'then options.operation_held=function()return false end end
        if mode~='default'then options.operation_execution={
            request=function()return {schema='fixture-proof-request'}end,
            accept=function(packet)granted=packet and packet.fixture==true;return true end,
            authorize_apply=function(body,intent,identity,control)
                authorizations=authorizations+1
                assert(body.cmd=='fixture' and intent.schema=='fixture-intent' and identity.command_sequence==1)
                assert(control.admitted and control.held and granted)
                if mode=='deny'then return false,'explicit refusal'end
                if mode=='late'then now=now+2.1 end
                if mode=='context'then context=string.rep('8',32)end
                if mode=='revoke'then service:revoke('callback revoked its owner')end
                if mode=='operation_false'then observed_operation_held=control.operation_held;return false,'operation is not held'end
                return true
            end,
            revoke=function()granted=false;revocations=revocations+1 end,
            status=function()return {granted=granted}end}
        end
        service=assert(Runtime.new(options))
        assert(service:observe(JSON.array({{event='fixture_observation'}}),{fixture=true}))
        for _=1,16 do now=now+.10;service:step()end
        assert(held,'operation callback released ordinary gameplay')
        assert(applied==(mode=='allow' and 1 or 0),'stale/default callback reached the physical adapter')
        assert(not service:status().control.ordinary_execution)
        if mode~='default'then assert(authorizations>0)end
        if mode=='operation_false'then assert(observed_operation_held==false)end
        if mode=='context' or mode=='revoke'then assert(not service:is_bound() and revocations>=2)end
    ''')


@pytest.mark.parametrize("fault", ["disconnect", "watchdog", "hold_notice"])
def test_service_fault_hard_holds_then_disarms_before_the_step_returns(runtime, fault):
    lua = runtime
    start(lua)
    lua.globals().fault = fault
    lua.execute('''
        local Runtime=require('durable_runtime')
        local Mux=require('hold_mux')
        now=0;connected=false;incoming={};physical=false;armed=false;revocation_order={}
        local binding={session_id=string.rep('1',32),admission_epoch=string.rep('2',32),
            context_generation=string.rep('3',32),binding_digest=string.rep('4',64)}
        local transport={init=function()connected=true end,connected=function()return connected end,pump=function()end,
            disconnect=function()connected=false;incoming={}end,receive=function()return table.remove(incoming,1)end,
            queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,
                receive_bytes=0,partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
            send=function(raw)
                local packet=assert(JSON.decode(raw))
                local response={protocol=packet.protocol,player=packet.player,seq=packet.seq,
                    operation_id=packet.operation_id,session_id=binding.session_id,
                    admission_epoch=binding.admission_epoch,ack='ACK',commands=JSON.array()}
                if packet.event=='hello'then
                    response.admission={state='admitted',client_nonce=packet.client_nonce,control_binding=binding}
                elseif packet.event=='control'then
                    response.recovery=JSON.object()
                    response.control={session_id=binding.session_id,admission_epoch=binding.admission_epoch,
                        context_generation=binding.context_generation,binding_digest=binding.binding_digest,
                        challenge=packet.control.challenge,authority='service',service_epoch=string.rep('5',32),
                        service_digest=string.rep('6',64),reason='paired service is current'}
                end
                incoming[#incoming+1]=assert(JSON.encode(response));return true
            end}
        local mux=Mux.new({owners={'startup','control','writer','lifecycle'},
            host={set_held=function(value)physical=value;return true end}})
        assert(mux:set('startup',true,'atomic startup'))
        service=assert(Runtime.new({protocol='fixture-runtime-v1',hold_event='fixture_hold',player='a',
            journal=journal,clock=function()return now end,transport=transport,server_host='localhost',server_port=1,
            read_hello=function()return {context_generation=binding.context_generation}end,
            metadata_matches=function()return true end,new_nonce=new_id,service_execution=true,
            host=mux:adapter('control'),operation_ready=function()return false,'no commands'end,
            on_revoke=function(reason)
                assert(mux:set('lifecycle',true,reason));revocation_order[#revocation_order+1]=physical and 'hold' or 'free'
                armed=false;revocation_order[#revocation_order+1]='disarm';return true
            end,
            executor_adapter={prepare=function()error('no command')end,classify=function()error('no command')end,
                apply=function()error('no command')end,receipt=function()error('no command')end}}))
        for i=1,12 do now=i*.1;assert(service:step())end
        assert(service:has_service_lease())
        assert(mux:set('startup',false,'startup complete'))
        assert(not physical);armed=true
        if fault=='disconnect'then connected=false
        elseif fault=='watchdog'then now=now+2
        else
            incoming[#incoming+1]=assert(JSON.encode({protocol='fixture-runtime-v1',player='a',
                session_id=binding.session_id,admission_epoch=binding.admission_epoch,event='fixture_hold',
                reason='server revoked service',commands=JSON.array()}))
        end
        service:step()
        assert(physical and not armed)
        assert(revocation_order[1]=='hold' and revocation_order[2]=='disarm')
        assert(not service:has_service_lease())
    ''')
