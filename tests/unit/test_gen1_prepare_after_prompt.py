"""Shared durable executor drives prompt closure before read-only preparation."""
import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import accepted, command, start


@pytest.fixture
def client(runtime):  # noqa: F811
    lua=runtime;start(lua)
    issued=command(1,cmd="native_trade_prepare",transaction_id="a"*32)
    event=lua.globals().append('{"event":"sync"}')
    assert accepted(lua.globals().accept(event,json.dumps([issued])))
    lua.globals().identifier=issued["command_id"]
    lua.execute('''
        phase='complete';close_writes=0;captures=0;readable=true
        closure={prepare=function(body,id)return {schema='rby-prompt-close-intent-v1',command_id=id.command_id}end,
            classify=function(body,intent,id)
                if phase=='complete'then return 'before',{}end
                if phase=='closing'then return 'armed',{schema='rby-prompt-close-pending-v1',command_id=id.command_id}end
                return 'after',{schema='closed'}
            end,
            apply=function()close_writes=close_writes+1;phase='closing'end,
            receipt=function()error('readiness must use fresh preparation')end}
        prompt={needs_closure=function()return true end,closure_adapter=function()return closure end}
        preparation={prepare=function()assert(readable,'readback unavailable');captures=captures+1;return {schema='read-only'}end,
            classify=function()return 'after',{schema='checkpoint'}end,
            receipt=function()return {schema='rby-native-ready-v1'}end,
            apply=function()error('read-only stage wrote')end}
        adapter=require('gen1_prepare_after_prompt').new(prompt,preparation)
        executor=require('command_executor').new(journal,adapter)
        function step()local ok,result=executor:step(identifier);return ok,JSON.encode(result)end
    ''')
    return lua


def test_no_closure_effect_before_durable_intent(client):
    g=client.globals();g.mode="before"
    ok,result=g.step();assert not ok and json.loads(result)["phase"]=="persist_intent"
    assert g.close_writes==g.captures==0


def test_readback_failure_after_native_return_cannot_repeat_closure(client):
    g=client.globals();ok,result=g.step()
    assert not ok and json.loads(result)["pending"] and g.close_writes==1 and g.captures==0
    g.phase="closed";g.readable=False
    ok,result=g.step();assert not ok and json.loads(result)["phase"]=="classify"
    assert g.close_writes==1
    g.readable=True
    ok,result=g.step();assert ok and json.loads(result)["outcome"]=="ACK"
    assert g.close_writes==1 and g.captures==1
    ok,result=g.step();assert ok and json.loads(result)["replayed"] and g.captures==1
