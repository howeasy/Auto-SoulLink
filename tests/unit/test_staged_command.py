"""Real journal/executor/store sequence with explicitly modeled physical children."""
import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import accepted, command, start


@pytest.fixture
def chain(runtime):  # noqa: F811
    lua=runtime;start(lua)
    issued=command(1,cmd='prepare')
    operation=lua.globals().append('{"event":"sync"}')
    assert accepted(lua.globals().accept(operation,json.dumps([issued])))
    lua.globals().identifier=issued['command_id']
    lua.execute('''
        Sequence=require('staged_command');Executor=require('command_executor')
        stage_disk=nil;stage_fault=false;point=0;first_running=false;save_fault=false;readable=true;context='context'
        effects={prompt=0,save=0};prepares={prompt=0,save=0}
        stage_backend={read=function()if stage_disk then return stage_disk end;return nil,'missing'end,
            replace=function(text)if stage_fault then return false,'stage publication failed'end;stage_disk=text;return true end,
            sha256=function(text)return hash_text(text)end}
        function make_chain()
            stage_store=assert(Store.open(stage_backend,binding,Sequence.initial()))
            local children={}
            for index,name in ipairs({'prompt','save'})do
                children[index]={name=name,adapter={
                    prepare=function()prepares[name]=prepares[name]+1;return {schema='child-intent-v1',before=index-1,after=index}end,
                    classify=function(body,intent,id)
                        if name=='prompt' and first_running then return 'armed',{schema='child-pending-v1',command_id=id.command_id}end
                        assert(point==intent.before or point==intent.after,'ambiguous child state')
                        return point==intent.before and 'before' or 'after',{point=point}
                    end,
                    apply=function(body,intent,id)
                        assert(stage_store:read().child_intent.after==intent.after,'effect preceded durable intent')
                        effects[name]=effects[name]+1
                        if name=='prompt'then first_running=true else point=intent.after;if save_fault then error('lost response after save')end end
                    end,
                    receipt=function(body,intent,observed)assert(readable,'readback failed');return observed end}}
            end
            sequence=Sequence.new({store=stage_store,stages=children,context=function()return context end,
                verify_completed=function()return readable and point==2 end})
            executor=Executor.new(journal,sequence)
        end
        make_chain()
        function step()local ok,result=executor:step(identifier);return ok,JSON.encode(result)end
        function returned()first_running=false;point=1 end
    ''')
    return lua


def step(lua):
    okay,result=lua.globals().step()
    return okay,json.loads(result)


def enter_save(lua):
    assert step(lua)[1]['pending']
    lua.globals().returned()
    assert step(lua)[1]['pending']
    assert lua.globals().sequence.completed(lua.globals().identifier,'prompt')


def test_child_effects_follow_durable_intents_and_complete_in_order(chain):
    enter_save(chain)
    assert step(chain)[0]
    assert dict(chain.globals().effects)=={'prompt':1,'save':1}
    assert step(chain)[1]['replayed']
    assert dict(chain.globals().effects)=={'prompt':1,'save':1}


def test_failed_child_intent_publication_prevents_all_effects(chain):
    chain.globals().stage_fault=True
    okay,result=step(chain)
    assert not okay and result['phase']=='classify'
    assert dict(chain.globals().effects)=={'prompt':0,'save':0}


def test_lost_save_response_recovers_from_readback_without_repeating_closed_prompt_or_save(chain):
    enter_save(chain)
    chain.globals().save_fault=True
    assert step(chain)[0] is False
    chain.globals().make_chain()
    assert step(chain)[0]
    assert dict(chain.globals().effects)=={'prompt':1,'save':1}


def test_receipt_failure_keeps_completed_physical_child_for_readback(chain):
    enter_save(chain)
    chain.globals().readable=False
    assert step(chain)[0] is False
    chain.globals().readable=True
    assert step(chain)[0]
    assert dict(chain.globals().effects)=={'prompt':1,'save':1}


def test_changed_context_cannot_continue_a_prepared_sequence(chain):
    enter_save(chain)
    chain.globals().context='replaced'
    assert step(chain)[0] is False
    assert chain.globals().effects['save']==0


@pytest.mark.parametrize('value',[None,'',1])
def test_missing_or_untyped_context_cannot_start_effects(chain,value):
    chain.globals().context=value
    assert step(chain)[0] is False
    assert dict(chain.globals().effects)=={'prompt':0,'save':0}


def test_final_readback_is_required_even_after_all_child_receipts_are_durable(chain):
    enter_save(chain)
    chain.globals().mode='before'  # fail outer receipt publication, after both physical stages
    assert step(chain)[0] is False
    chain.globals().point=99
    okay,result=step(chain)
    assert not okay
    assert dict(chain.globals().effects)=={'prompt':1,'save':1}
