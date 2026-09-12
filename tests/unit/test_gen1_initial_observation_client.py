import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import start


@pytest.fixture
def observer(runtime):  # noqa: F811
    lua=runtime;start(lua)
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
    before=observer.globals().disk;observer.globals().mode='before'
    assert observer.globals().observe(True)[0] is False
    assert observer.globals().disk==before


def test_replaced_context_cannot_reuse_the_old_initial_baseline(observer):
    assert observer.globals().observe(True)==(True,True)
    observer.execute("context.context_generation=string.rep('c',32)")
    assert observer.globals().observe(True)[0] is False
    assert len(payload(observer)['outbox'])==1
