"""A slow but timely control roundtrip cannot starve durable receipt delivery."""

from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime as runtime


def test_control_and_large_receipt_queue_alternate_without_granting_frames(runtime):
    lua = runtime
    start(lua)
    lua.execute("""
        local Runtime=require("durable_runtime")
        now=0;connected=false;incoming={};sent={};held=true;issued=false
        local binding={session_id=string.rep('1',32),admission_epoch=string.rep('2',32),
            context_generation=string.rep('3',32),binding_digest=string.rep('4',64)}
        local transport={init=function()connected=true end,connected=function()return connected end,
            pump=function()end,disconnect=function()connected=false;incoming={}end,
            receive=function()return table.remove(incoming,1)end,
            queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,
                receive_bytes=0,partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
            send=function(raw)
                local packet=assert(JSON.decode(raw));sent[#sent+1]=packet.event
                local response={protocol=packet.protocol,player=packet.player,seq=packet.seq,operation_id=packet.operation_id,
                    session_id=binding.session_id,admission_epoch=binding.admission_epoch,ack="ACK",commands=JSON.array()}
                if packet.event=="hello"then response.admission={state="admitted",client_nonce=packet.client_nonce,control_binding=binding}
                elseif packet.event=="control"then
                    response.recovery=JSON.object()
                    response.control={session_id=binding.session_id,admission_epoch=binding.admission_epoch,
                        context_generation=binding.context_generation,binding_digest=binding.binding_digest,
                        challenge=packet.control.challenge,authority="hold",reason="owned test hold"}
                elseif packet.event=="observation" and not issued then
                    local cmd={cmd="fixture",command_id=string.rep('5',32),command_sequence=1,command_index=1}
                    for _,key in ipairs({'protocol','player','seq','operation_id','session_id','admission_epoch'})do cmd[key]=response[key]end
                    response.commands=JSON.array({cmd});issued=true
                end
                incoming[#incoming+1]=assert(JSON.encode(response));return true
            end}
        service=assert(Runtime.new({protocol='fixture-runtime-v1',hold_event='fixture_hold',player='a',
            journal=journal,clock=function()return now end,transport=transport,server_host='localhost',server_port=1,
            read_hello=function()return {context_generation=binding.context_generation}end,
            metadata_matches=function()return true end,new_nonce=new_id,
            host={set_held=function(value)held=value;return true end},operation_ready=function()return true end,
            executor_adapter={prepare=function()return {schema='fixture'}end,
                classify=function()return 'after',{verified=true}end,apply=function()error('must never write')end,
                receipt=function()return {schema='fixture-proof-v1',payload=string.rep('AB',32768)}end}}))
        assert(service:observe(JSON.array({{event='observation'}}),{fixture=true}))
        for i=1,12 do now=i*.30;assert(service:step())end
        local counts={};for _,event in ipairs(sent)do counts[event]=(counts[event]or 0)+1 end
        assert(counts.observation==1 and counts.command_ack==1 and counts.control>=2,'control starved durable receipts: '..assert(JSON.encode(sent))..assert(JSON.encode(service:status({summary=true}))))
        assert(held and service:is_bound())
        assert(service:status().execution.receipt.payload==string.rep('AB',32768))
        assert(service:status({summary=true}).execution.receipt==nil)
        service:revoke('fixture ends');assert(not service:is_bound())
    """)
