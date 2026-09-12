"""Real client journal/window integration around a deterministic bounded host."""

import json

import pytest

from server.gen1_launcher import ORDINARY_FILES, build_configuration
from tests.unit import test_gen1_engine_signals_client as source_fixtures
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime as runtime
from tests.unit.test_gen1_sessions import contract

source_probe = source_fixtures.probe


def setup(lua, *, auxiliary=False):
    start(lua)
    lua.globals().use_auxiliary = auxiliary
    lua.execute('''
        Frame=require('gen1_frame_client');Canonical=require('journal_document')
        journal=assert(Journal.open(store,new_id,{acknowledge_event=function(event,op,baseline)
            if event.event=='frame_complete'then return Frame.acknowledge_event(event,op,baseline)end
        end}))
        frame=100;now=0;steps=0;paused=false;safe=true;hook_pending=JSON.array();drains=0;emit=false
        context={context_generation=string.rep('a',32),physical_instance=string.rep('1',32),
            save_identity={ot_id='0000',trainer_name='SAME'}}
        owner={owner_id=context.physical_instance,capability_id='bizhawk-2.11.1-gambatte-exclusive-hold-v1',
            process_id=123,held=true}
        binding={binding_digest=string.rep('b',64),context_generation=context.context_generation,
            session_id=string.rep('c',32),admission_epoch=string.rep('d',32)}
        emu={framecount=function()return frame end}
        function boundary()return {schema='rby-frame-boundary-v1',context_generation=context.context_generation,
            final_sha1=string.rep('e',40),frame=frame,host=owner}end
        function inventory()
            if not safe then return nil end
            local result=boundary();result.schema='rby-initial-observation-v1';result.source={fixture=true};return result
        end
        local baseline={initial_inventory={phase='acknowledged',payload={payload=inventory()}},
            bootstrap={phase='acknowledged'}}
        assert(journal:append_many(JSON.array(),baseline))
        hooks={peek=function()return assert(JSON.decode(assert(JSON.encode(hook_pending))))end,
            status=function()return {pending=#hook_pending}end,
            drain=function(_,expected)
                assert(Canonical.encode(expected)==Canonical.encode(hook_pending))
                local p=progress_store and progress_store:read().progress or store:read().observation.frame_progress
                assert(p.frame==frame and #p.active.signals>=#expected,'drained before durable frame publication')
                drains=drains+1;hook_pending=JSON.array();return true
            end,
            batch=function(_,signals,sequence)return {schema='rby-engine-signals-v1',sequence=sequence,signals=signals}end}
        if use_auxiliary then
            progress_disk=nil;progress_writes=0;aux_mode='ok'
            progress_backend={read=function()return progress_disk,progress_disk==nil and 'missing'or nil end,
                replace=function(text)
                    progress_writes=progress_writes+1
                    if aux_mode=='before'then return false,'auxiliary publication failed'end
                    progress_disk=text;return true
                end,sha256=backend.sha256}
            function open_progress()return assert(Store.open(progress_backend,{schema='frame-fixture'},Frame.initial()))end
            progress_store=open_progress()
        end
        local options={journal=journal,progress_store=progress_store,clock=function()return now end,new_nonce=new_id,
            inflight=function()return rpc_inflight==true end,
            observe=function(events,baseline)
                if service then return service:observe(events,baseline)end
                local ids=journal:append_many(events,baseline)
                if fail_aux_after_publish then aux_mode='before'end
                return ids
            end,
            owned=function()return context end,boundary=boundary,inventory=inventory,signals=function()return hooks end,
            host={status=function()return {user_paused=paused,physical_stop_verified=true}end},
            step_one=function(selected)
                assert(client:authorize(selected,{frame=frame}),'bounded host refused authority')
                frame=frame+1;steps=steps+1
                if emit then hook_pending[#hook_pending+1]={kind='fixture',frame=frame}end
                return true
            end}
        frame_options=options;client=Frame.new(options)
        function grant(count)
            local request=assert(client:request(binding,{admitted=true,held=true}))
            client:control(binding)
            local window=request.window
            local packet={schema=window.schema,scope=window.scope,challenge=window.challenge,
                frames=count or 2,ttl_ms=1000,proof_digest=hash_text(Canonical.encode(request.evidence))}
            packet=assert(JSON.decode(assert(JSON.encode(packet))))
            assert(client:accept(packet));return request,packet
        end
        function progress()return store:read().observation.frame_progress end
        function tick()now=now+.02;return client:step(true)end
        function completion()
            local events=assert(journal:pending_events())
            for _,event in ipairs(events)do if event.payload.event=='frame_complete'then return event end end
        end
    ''')


@pytest.mark.parametrize('sparse', [False, True])
def test_credits_close_real_durable_event_and_ack_precedes_next_range(runtime, sparse):
    setup(runtime)
    runtime.globals().safe = not sparse
    runtime.execute('''
        local request=grant(2)
        assert(request.evidence.sequence==1 and request.evidence.boundary.frame==100)
        assert(tick() and frame==101 and drains==1 and progress().phase=='active')
        assert(tick() and frame==102 and drains==2 and progress().phase=='queued')
        local event=assert(completion());local receipt=event.payload.receipt
        assert(receipt.before==100 and receipt.after==102 and receipt.steps==2 and receipt.sequence==1)
        assert(receipt.observations_digest==hash_text(Canonical.encode(event.payload.bundle)))
        assert((event.payload.bundle.inventory~=JSON.null)==safe)
        assert(event.payload.bundle.engine_signals==JSON.null)
        assert(client:request(binding,{admitted=true,held=true})==nil and client:blocks_commands())
        assert(journal:accept_response(event.operation_id,JSON.array()))
        assert(progress().phase=='idle' and progress().sequence==1 and not client:blocks_commands())
        local next_request=grant(1)
        assert(next_request.evidence.sequence==2 and next_request.evidence.boundary.frame==102)
        assert(tick() and frame==103)
    ''')


def test_source_hooks_persist_before_drain_and_force_early_range_closure(runtime):
    setup(runtime)
    runtime.execute('''
        emit=true;safe=false;grant(20)
        assert(tick() and frame==101 and drains==1)
        local event=completion();assert(event.payload.receipt.steps==1)
        local source=event.payload.bundle.engine_signals
        assert(source.sequence==1 and #source.signals==1 and source.signals[1].frame==101)
        assert(store:read().observation.engine_signals.sequence==1)
        assert(#hook_pending==0 and progress().phase=='queued')
    ''')


@pytest.mark.parametrize('fault', ['expire', 'near-expiry', 'revoke', 'command', 'event', 'pause'])
def test_interruptions_close_used_range_without_extra_steps(runtime, fault):
    setup(runtime)
    runtime.globals().fault = fault
    runtime.execute('''
        grant(20);assert(tick() and frame==101)
        if fault=='expire'then now=2
        elseif fault=='near-expiry'then now=.94
        elseif fault=='revoke'then client:revoke('disconnect')
        elseif fault=='command'then
            local sync=assert(journal:append({event='sync'}))
            assert(journal:accept_response(sync,JSON.array({{command_id=string.rep('f',32),command_sequence=1,
                body={cmd='force_faint'}}})))
        elseif fault=='event'then assert(journal:append({event='other'}))
        else paused=true;now=2 end
        assert(tick() and frame==101 and progress().phase=='queued')
        assert(completion().payload.receipt.steps==1)
    ''')


@pytest.mark.parametrize('fault', ['foreign-frame', 'disk-failure', 'wrong-proof', 'wrong-scope', 'unknown-revoke'])
def test_foreign_or_uncertain_state_refuses_further_physical_execution(runtime, fault):
    setup(runtime)
    runtime.globals().fault = fault
    runtime.execute('''
        if fault=='wrong-proof' or fault=='wrong-scope'then
            local request=assert(client:request(binding,{admitted=true,held=true}));client:control(binding)
            local packet={schema=request.window.schema,scope=request.window.scope,challenge=request.window.challenge,
                frames=2,ttl_ms=1000,proof_digest=hash_text(Canonical.encode(request.evidence))}
            if fault=='wrong-proof'then packet.proof_digest=string.rep('f',64)else packet.scope.phase='other'end
            packet=assert(JSON.decode(assert(JSON.encode(packet))))
            assert(client:accept(packet)==false and frame==100)
        elseif fault=='unknown-revoke'then
            assert(client:request(binding,{admitted=true,held=true}));client:revoke('lost reply')
            assert(client:step(false)==false and frame==100)
        else
            grant(2)
            if fault=='foreign-frame'then frame=frame+1 else mode='before'end
            assert(tick()==false)
            local stopped=frame;assert(tick()==false and frame==stopped)
        end
    ''')


def test_explicit_decline_and_sync_poll_do_not_invent_or_starve_frames(runtime):
    setup(runtime)
    runtime.execute('''
        assert(client:request(binding,{admitted=true,held=true}));client:control(binding)
        assert(client:accept(nil) and progress().phase=='idle' and frame==100)
        grant(2)
        assert(journal:append({event='sync'}))
        assert(tick() and frame==101 and tick() and frame==102)
        assert(completion().payload.receipt.steps==2)
    ''')


def test_launcher_selects_complete_ordinary_closure_explicitly():
    config = build_configuration('a' * 32, contract('yellow', 'yellow'), 'a',
                                 initial_observations=True, ordinary_frames=True)
    assert config['ordinary_frames'] is True
    serialized = json.dumps(config['files'])
    assert all(name in serialized for name in ORDINARY_FILES)
    with pytest.raises(ValueError):
        build_configuration('a' * 32, contract('yellow', 'yellow'), 'a', ordinary_frames=True)


@pytest.mark.parametrize('control_delay', [0, 0.08], ids=['normal-control', 'control-slower-than-heartbeat'])
def test_real_durable_runtime_carries_control_grants_and_frame_ack_before_command_effect(runtime, control_delay):
    setup(runtime)
    runtime.globals().control_delay = control_delay
    runtime.execute('''
        local Runtime=require('durable_runtime')
        connected=false;incoming={};completed=0;applied=0;issued=false;frame_at_apply=nil
        local transport={init=function()connected=true end,connected=function()return connected end,pump=function()end,
            disconnect=function()connected=false;incoming={}end,receive=function()return table.remove(incoming,1)end,
            queue_status=function()return {send_lines=0,send_bytes=0,send_offset=0,receive_lines=0,
                receive_bytes=0,partial_receive_bytes=0,pending_receive_bytes=0,ready_receive_bytes=0}end,
            send=function(raw)
                local packet=assert(JSON.decode(raw))
                local response={protocol=packet.protocol,player=packet.player,seq=packet.seq,operation_id=packet.operation_id,
                    session_id=binding.session_id,admission_epoch=binding.admission_epoch,ack='ACK',commands=JSON.array()}
                if packet.event=='hello'then
                    response.admission={state='admitted',client_nonce=packet.client_nonce,control_binding=binding}
                elseif packet.event=='control'then
                    now=now+control_delay
                    response.recovery=JSON.object()
                    response.control={session_id=binding.session_id,admission_epoch=binding.admission_epoch,
                        context_generation=binding.context_generation,binding_digest=binding.binding_digest,
                        challenge=packet.control.challenge,authority='hold',reason='bounded ordinary fixture'}
                    local operation=packet.operation_execution
                    if operation and operation~=JSON.null then
                        assert(operation.evidence.schema=='rby-frame-request-v1')
                        local window=operation.window
                        response.operation_execution={schema=window.schema,scope=window.scope,challenge=window.challenge,
                            frames=2,ttl_ms=1000,proof_digest=hash_text(Canonical.encode(operation.evidence))}
                    end
                elseif packet.event=='frame_complete'then
                    completed=completed+1
                    assert(packet.receipt.after==frame and packet.receipt.steps<=2)
                    assert(packet.receipt.observations_digest==hash_text(Canonical.encode(packet.bundle)))
                    if not issued then
                        local command={cmd='fixture',command_id=string.rep('f',32),command_sequence=1,command_index=1}
                        for _,key in ipairs({'protocol','player','seq','operation_id','session_id','admission_epoch'})do command[key]=response[key]end
                        response.commands=JSON.array({command});issued=true
                    end
                end
                incoming[#incoming+1]=assert(JSON.encode(response));return true
            end}
        local routed=false
        local operations={
            request=function(b,c)local value=client:request(b,c);routed=value~=nil;return value end,
            accept=function(packet,b)
                client:control(b)
                if routed then routed=false;return client:accept(packet)end
                assert(packet==nil);return true
            end,
            revoke=function(why)client:revoke(why)end,
            status=function()return client:status()end,
            authorize_apply=function()return not client:blocks_commands()end}
        service=assert(Runtime.new({protocol='fixture-runtime-v1',hold_event='fixture_hold',player='a',journal=journal,
            clock=function()return now end,transport=transport,server_host='localhost',server_port=1,
            control_interval=.05,sync_interval=.3,read_hello=function()return {context_generation=context.context_generation}end,
            metadata_matches=function()return true end,new_nonce=new_id,host={set_held=function(value)assert(value);return true end},
            operation_execution=operations,operation_ready=function()return not client:blocks_commands()end,
            executor_adapter={prepare=function()assert(not client:blocks_commands());return {schema='fixture-intent'}end,
                classify=function()return applied==1 and 'after' or 'before',{applied=applied}end,
                apply=function()assert(progress().phase=='idle' and completed>0);applied=applied+1;frame_at_apply=frame end,
                receipt=function()return {schema='fixture-receipt',applied=applied}end}}))
        for _=1,100 do
            now=now+.01;assert(service:step())
            local ok,why=client:step(service:is_bound())
            assert(ok,tostring(why)..' '..assert(JSON.encode(service:status())))
        end
        assert(completed>=1 and steps>=2 and applied==1 and frame_at_apply>=102)
        assert(not service:status().control.ordinary_execution)
    ''')


def test_real_source_hook_peek_is_read_only_and_exact_drain_is_held(source_probe):
    source_fixtures.load_point(source_probe)
    before = source_probe.globals().disk
    source_probe.execute('''
        held=false;fire('battle_faint')
        assert(probe:status().pending==1 and not probe:status().failed)
        assert(not pcall(function()probe:peek()end))
        held=true;snapshot=probe:peek()
        local changed=probe:peek();changed[1].frame=101
        assert(not pcall(function()probe:drain(changed)end))
        assert(probe:status().pending==1)
        local batch=probe:batch(snapshot,1)
        assert(batch.sequence==1 and #batch.signals==1)
        assert(probe:drain(snapshot)and probe:status().pending==0)
    ''')
    assert source_probe.globals().disk == before


def test_auxiliary_step_journal_avoids_rewriting_enrollment_until_real_event(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(2);local original=disk;local count=progress_writes
        assert(tick()and frame==101 and disk==original and progress_writes==count+1)
        assert(progress_store:read().progress.frame==101)
        assert(tick()and frame==102 and disk~=original)
        local event=completion();assert(event.payload.receipt.steps==2)
        assert(journal:accept_response(event.operation_id,JSON.array()))
        assert(client:status().phase=='idle')
        local request=grant(1);assert(request.evidence.sequence==2 and request.evidence.boundary.frame==102)
        assert(tick()and frame==103)
    ''')


def test_main_publication_and_ack_recover_across_auxiliary_failure_without_reexecution(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(1);fail_aux_after_publish=true
        assert(tick()==false and frame==101)
        local event=assert(completion());assert(event.payload.receipt.steps==1)
        aux_mode='ok';fail_aux_after_publish=false;progress_store:close()
        progress_store=open_progress();frame_options.progress_store=progress_store
        client=Frame.new(frame_options)
        assert(client:status().phase=='queued'and client:blocks_commands())
        assert(client:step(false)and frame==101 and #journal:pending_events()==1)
        assert(journal:accept_response(event.operation_id,JSON.array()))
        -- Main ACK may also precede any auxiliary update; it is authoritative.
        client=Frame.new(frame_options)
        assert(client:status().phase=='idle'and frame==101)
        local request=grant(1);assert(request.evidence.sequence==2)
        assert(tick()and frame==102)
    ''')


def test_auxiliary_failure_after_step_latches_before_another_frame(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(2);aux_mode='before';local original=disk
        assert(tick()==false and frame==101 and disk==original)
        assert(tick()==false and frame==101 and completion()==nil)
    ''')


def test_source_is_persisted_but_heavy_closure_waits_for_inflight_response(runtime):
    setup(runtime, auxiliary=True)
    runtime.execute('''
        grant(20);emit=true;rpc_inflight=true
        assert(tick()and frame==101 and completion()==nil)
        assert(progress_store:read().progress.active.signals[1].frame==101 and #hook_pending==0)
        assert(tick()and frame==101 and client:blocks_commands())
        rpc_inflight=false
        assert(tick()and frame==101 and completion().payload.receipt.steps==1)
    ''')
