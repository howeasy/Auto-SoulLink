import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import start


@pytest.fixture
def stream(runtime):  # noqa: F811
    lua = runtime; start(lua)
    lua.execute('''
        Stream=require('observation_stream');context={generation='one'};ready=false;frame=1;fault=nil;sample_count=0
        stream=Stream.new({journal=journal,key='test_stream',event='test_observation',
            owned=function()return context end,
            seed=function()if ready then return {sequence=0,operation_id=string.rep('f',32),observation={frame=0}}end end,
            sample=function(previous)
                sample_count=sample_count+1
                if fault=='sample'then context.generation='two'end
                if fault=='journal'then assert(journal:append({event='other'}, {other=true}))end
                if frame==previous.frame then return nil end
                return {frame=frame}
            end,
            verify=function(point)
                if fault=='verify'then context.generation='two'end
                return point.frame==frame
            end})
        journal=assert(Journal.open(store,new_id,stream))
        function step()return pcall(function()return stream:step()end)end
        function reopen_stream_journal()
            store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id,stream))
        end
    ''')
    return lua


def saved(lua):
    return json.loads(lua.globals().disk)['document']['payload']


def test_waits_for_seed_and_keeps_one_event_in_flight_until_exact_ack(stream):
    assert stream.globals().step() == (True, False)
    stream.globals().ready = True
    assert stream.globals().step() == (True, True)
    first = saved(stream)['outbox'][0]
    assert first['payload']['payload']['sequence'] == 1
    stream.globals().frame = 2
    assert stream.globals().step() == (True, False)
    assert stream.globals().sample_count == 1
    assert stream.globals().accept(first['operation_id'], '[]')[0] is True
    assert stream.globals().step() == (True, True)
    second = saved(stream)['outbox'][0]
    assert second['payload']['payload']['previous_operation_id'] == first['operation_id']
    assert second['payload']['payload']['sequence'] == 2


@pytest.mark.parametrize('fault', ['sample', 'verify'])
def test_callback_context_change_cannot_publish(stream, fault):
    stream.globals().ready = True; stream.globals().fault = fault
    before = stream.globals().disk
    assert stream.globals().step()[0] is False
    assert stream.globals().disk == before


@pytest.mark.parametrize('mode', ['before', 'after', 'corrupt'])
def test_publication_fault_holds_until_reopen_without_silent_baseline_progress(stream, mode):
    stream.globals().ready = True; stream.globals().mode = mode
    assert stream.globals().step()[0] is False
    assert stream.globals().step()[0] is False
    if mode == 'before': assert not saved(stream)['outbox']
    elif mode == 'after':
        state = saved(stream)
        assert state['observation']['test_stream']['payload'] == state['outbox'][0]['payload']
        stream.globals().mode = 'ok'
        stream.globals().reopen_stream_journal()
        event = saved(stream)['outbox'][0]
        assert stream.globals().accept(event['operation_id'], '[]')[0] is True
        assert saved(stream)['observation']['test_stream']['operation_id'] == event['operation_id']


def test_new_context_cannot_replay_a_queued_baseline_as_a_new_observation(stream):
    stream.globals().ready = True
    assert stream.globals().step() == (True, True)
    stream.execute("context.generation='replacement'")
    assert stream.globals().step()[0] is False
    assert len(saved(stream)['outbox']) == 1


def test_acknowledged_sample_does_not_emit_when_binding_returns_no_change(stream):
    stream.globals().ready = True
    assert stream.globals().step() == (True, True)
    event = saved(stream)['outbox'][0]
    assert stream.globals().accept(event['operation_id'], '[]')[0] is True
    before = stream.globals().disk
    assert stream.globals().step() == (True, False)
    assert stream.globals().disk == before


def test_callback_journal_mutation_cannot_be_overwritten_by_a_stale_baseline(stream):
    stream.globals().ready = True; stream.globals().fault = 'journal'
    assert stream.globals().step()[0] is False
    state = saved(stream)
    assert state['observation'] == {'other': True}
    assert [event['payload']['event'] for event in state['outbox']] == ['other']


def test_context_change_during_storage_publication_retains_exact_pending_evidence(stream):
    stream.globals().ready = True
    stream.execute('''
        local replace=backend.replace
        backend.replace=function(text)local result=replace(text);context.generation='two';return result end
    ''')
    assert stream.globals().step()[0] is False
    state = saved(stream)
    assert state['observation']['test_stream']['payload'] == state['outbox'][0]['payload']
    assert stream.globals().step()[0] is False
