import json

import pytest

from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401


@pytest.fixture
def observer(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute('''
        frame=100;context={context_generation=string.rep('a',32)};fault=nil
        emu={framecount=function()return frame end};gameinfo={getromhash=function()return string.rep('b',40)end}
        package.loaded.gen1_full_save={capture=function()
            if fault=='context'then context.context_generation=string.rep('c',32)end
            if fault=='frame'then frame=frame+1 end
            return {schema='explicit-source-fixture'}
        end}
        Observe=require('gen1_initial_observation')
        observer=Observe.new({journal=journal,memory={isPartyWriteSafe=function()return true end},variant='yellow',
            owned=function()return context end,host={status=function()return {physical_stop_verified=true,
                owner_id='owner',capability_id='fixture',process_id=1}end}})
        function observe(admitted)return pcall(function()return observer:step(admitted)end)end
    ''')
    return lua


def payload(lua):
    return json.loads(lua.globals().disk)['document']['payload']


def test_initial_observation_waits_for_admission_and_publishes_baseline_with_event(observer):
    assert observer.globals().observe(False)==(True,False)
    assert not payload(observer)['outbox']
    assert observer.globals().observe(True)==(True,True)
    saved=payload(observer)
    assert saved['observation']['initial_inventory']['payload']==saved['outbox'][0]['payload']
    assert observer.globals().observe(True)==(True,False)
    assert len(payload(observer)['outbox'])==1


@pytest.mark.parametrize('fault',['context','frame'])
def test_changed_owner_or_frame_during_snapshot_cannot_publish(observer,fault):
    observer.globals().fault=fault
    assert observer.globals().observe(True)[0] is False
    assert not payload(observer)['outbox'] and not payload(observer)['observation']


def test_store_failure_cannot_advance_the_observation_baseline(observer):
    before = observer.globals().disk
    observer.globals().mode = 'before'
    assert observer.globals().observe(True)[0] is False
    assert observer.globals().disk==before


def test_replaced_context_cannot_reuse_the_old_initial_baseline(observer):
    assert observer.globals().observe(True)==(True,True)
    observer.execute("context.context_generation=string.rep('c',32)")
    assert observer.globals().observe(True)[0] is False
    assert len(payload(observer)['outbox'])==1


def test_free_observation_ack_persists_the_exact_server_cursor(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute("""
        package.loaded.gen1_full_save={}
        Observe=require('gen1_initial_observation')
        store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id,Observe))
        local baseline=assert(store:read()).observation
        baseline.observation_sequence=1
        operation=assert(journal:append({event='observation',schema='rby-observation-v1',sequence=1,frame=123},baseline))
        assert(journal:accept_response(operation,JSON.array()))
    """)
    saved = payload(lua)["observation"]
    assert saved["observation_cursor"] == {
        "sequence": 1,
        "operation_id": lua.globals().operation,
        "frame": 123,
    }
    assert saved["observation_sequence"] == 1 and payload(lua)["outbox"] == []


def test_deferred_inventory_ack_durably_forces_a_later_unchanged_resend(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute("""
        package.loaded.gen1_full_save={}
        Observe=require('gen1_initial_observation')
        store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id,Observe))
        local baseline=assert(store:read()).observation
        baseline.observation_sequence=1
        event={event='observation',schema='rby-observation-v1',sequence=1,frame=120,
            inventory={schema='fixture-point',source='unchanged'}}
        first=assert(journal:append(event,baseline))
        local deferred={schema='rby-observation-result-v1',operation_id=first,
            sequence=1,frame=120,inventory_status='deferred'}
        assert(journal:accept_response(first,JSON.array(),deferred))
        first_baseline=assert(store:read()).observation
        assert(first_baseline.pending_inventory_retry.operation_id==first)
        baseline=assert(store:read()).observation
        baseline.observation_sequence=2
        second=assert(journal:append({event='observation',schema='rby-observation-v1',sequence=2,
            frame=150,inventory={schema='fixture-point',source='unchanged'}},baseline))
        local accepted={schema='rby-observation-result-v1',operation_id=second,
            sequence=2,frame=150,inventory_status='recorded'}
        assert(journal:accept_response(second,JSON.array(),accepted))
        final=assert(store:read()).observation
    """)
    first = json.loads(lua.eval("JSON.encode(first_baseline)"))
    assert first["pending_inventory_retry"]["sequence"] == 1
    final = json.loads(lua.eval("JSON.encode(final)"))
    assert "pending_inventory_retry" not in final and final["observation_cursor"]["sequence"] == 2
    assert payload(lua)["outbox"] == []


def test_acknowledged_free_initial_payload_compacts_to_a_bound_digest_only_after_adoption(runtime):  # noqa: F811
    lua = runtime
    lua.execute("""
        package.loaded.gen1_full_save={}
        Observe=require('gen1_initial_observation')
        entry={phase='acknowledged',operation_id=string.rep('9',32),payload={event='initial_observation',payload={
            schema='rby-initial-observation-v1',context_generation=string.rep('a',32),
            final_sha1=string.rep('b',40),frame=123,source={large=string.rep('FF',32768)}}}}
        before=assert(JSON.encode(entry));cursor=Observe.initial_cursor(entry)
        compact,changed=Observe.compact_initial(entry,function(value)
            assert(value==assert(require('journal_document').encode(entry.payload.payload)))
            return string.rep('c',64)
        end)
        compact_again,changed_again=Observe.compact_initial(compact,function()error('already compact')end)
    """)
    assert lua.globals().changed is True and lua.globals().changed_again is False
    compact = json.loads(lua.eval("JSON.encode(compact)"))
    assert compact == {
        "schema": "rby-initial-observation-cursor-v1", "phase": "acknowledged",
        "operation_id": "9" * 32, "context_generation": "a" * 32,
        "final_sha1": "b" * 40, "frame": 123, "payload_digest": "c" * 64,
    }
    assert lua.eval("Observe.initial_cursor(compact_again).frame") == 123
    assert "payload" not in compact and len(lua.globals().before) > 65_000


def test_free_service_restart_accepts_only_the_same_compact_context(runtime):  # noqa: F811
    lua = runtime
    lua.execute("""
        package.loaded.gen1_full_save={}
        Observe=require('gen1_initial_observation')
        context={context_generation=string.rep('a',32)}
        baseline={initial_inventory={schema=Observe.COMPACT,phase='acknowledged',operation_id=string.rep('9',32),
            context_generation=context.context_generation,final_sha1=string.rep('b',40),frame=123,
            payload_digest=string.rep('c',64)},bootstrap={phase='acknowledged'}}
        journal={store={read=function()return {observation=baseline}end}}
        restarted=Observe.new({journal=journal,memory={},variant='yellow',free_service=true,
            owned=function()return context end,host={}})
        ok,value=pcall(function()return restarted:step(true)end)
        context.context_generation=string.rep('d',32)
        foreign=pcall(function()return restarted:step(true)end)
    """)
    assert lua.globals().ok is True and lua.globals().value is False
    assert lua.globals().foreign is False
