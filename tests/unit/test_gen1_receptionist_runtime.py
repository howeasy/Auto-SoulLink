"""Real journal/UI ownership policies with explicitly modeled query/host signals."""
import copy
import secrets
from types import SimpleNamespace

import pytest

from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_native_execution import NativeExecutionPolicy, SCHEMA
from server.gen1_native_policy import NativeTradePolicy
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_trade import TradeCase
from tests.unit.test_gen1_trade_preparation import checkpoint


@pytest.fixture
def ui(tmp_path):
    run=TradeCase(tmp_path);run.admit('a');run.admit('b')
    manifests={p:companion_profiles()[v]['manifest'] for p,v in run.variants.items()}
    for p in manifests:run.policy.rules[p].rom_sha1=manifests[p]['final_sha1']
    model=SimpleNamespace(policy=run.policy,contexts=run.policy.contexts,
        original={'rules':{'parties':{p:[raw.hex().upper()] for p,raw in run.blobs.items()}}})
    points={p:checkpoint(model,p) for p in ('a','b')}
    execution=NativeExecutionPolicy(rules=run.policy.rules,manifests=manifests);execution.bind(run.runtime)
    policy=NativeTradePolicy();run.runtime.trade.policy.policy=policy
    policy.configure(execution,read_checkpoints=lambda:points);controller=policy.install_receptionist()
    manifest=manifests['a'];context=run.policy.contexts['a']
    event={'event':'receptionist_entered','payload':{'schema':'rby-receptionist-entry-v1',
        'context_generation':context.context_generation,'final_sha1':manifest['final_sha1'],'checkpoint':points['a'],
        'query':{'schema':'rby-receptionist-query-v1','pc':0x40,'bank':manifest['receptionist']['entry']['bank'],
                 'caller':manifest['receptionist']['query_return'],'overlay_hex':'534C543101010706'+'00'*8}}}
    yield run,controller,execution,event
    run.close()


def opened(ui):
    run,controller,execution,event=ui;operation=secrets.token_hex(16)
    result=controller.start('a',operation,event)
    command=run.runtime.journal.command('a',run.runtime.journal.pending_ids('a')[0])
    own=run.policy.contexts['a']
    intent={'schema':'rby-receptionist-intent-v1','command_id':command['command_id'],'command_sequence':command['command_sequence'],
            'body_digest':digest(command['body']),'context_generation':own.context_generation,'token_hex':'AABBCCDD'}
    evidence={'schema':SCHEMA,'command_id':command['command_id'],'command_sequence':command['command_sequence'],
              'context_generation':own.context_generation,'final_sha1':event['payload']['final_sha1'],
              'host':{'owner_id':own.physical_instance,'capability_id':'bizhawk-2.11.1-gambatte-exclusive-hold-v1',
                      'process_id':123,'frame':100,'steps':0,'held':True,'bounded':True,'failed':False},
              'native':{'phase':'before','intent':intent,'checkpoint':event['payload']['checkpoint'],'query':event['payload']['query']}}
    return operation,result,command,evidence


def grant(ui,command,evidence):
    run,_,execution,_=ui
    return execution('a',command,evidence,run.runtime.state().document(),run.runtime.gate.sessions['a'].metadata['control_binding'])


def test_query_is_durable_replay_deduplicated_and_generates_only_one_ui_command(ui):
    operation,result,command,evidence=opened(ui)
    run,controller,_,event=ui
    assert controller.start('a',operation,event)==result
    assert run.runtime.journal.pending_ids('a')==(command['command_id'],)
    assert command['body']['eligible_mask']==1
    assert grant(ui,command,evidence).scope['phase']=='native_receptionist'
    assert run.runtime.state().barrier.ticket() is None


@pytest.mark.parametrize('fault',['caller','bank','generation','point','context'])
def test_unverified_query_cannot_create_a_native_obligation(ui,fault):
    run,controller,_,event=ui;event=copy.deepcopy(event)
    if fault in {'caller','bank'}:event['payload']['query'][fault]+=1
    elif fault=='generation':event['payload']['query']['overlay_hex']='534C543101010707'+'00'*8
    elif fault=='point':event['payload']['checkpoint']['map']+=1
    else:event['payload']['context_generation']='f'*32
    with pytest.raises(JournalError):controller.start('a',secrets.token_hex(16),event)
    assert not run.runtime.journal.pending_ids('a')


def test_native_cancel_return_is_acknowledged_without_creating_trade_or_saving(ui):
    _,_,command,evidence=opened(ui);assert grant(ui,command,evidence)
    run,controller,_,event=ui
    receipt={'schema':'rby-receptionist-return-v1','command_id':command['command_id'],
             'command_sequence':command['command_sequence'],'context_generation':event['payload']['context_generation'],
             'final_sha1':event['payload']['final_sha1'],'checkpoint':event['payload']['checkpoint'],
             'sequence':['after_query','menus_restored'],'offer_operation_id':None,'frame':110,'token_hex':'AABBCCDD'}
    message={'event':'command_ack','command_id':command['command_id'],'command_sequence':command['command_sequence'],
             'outcome':'ACK','receipt':receipt}
    assert controller.acknowledge('a',secrets.token_hex(16),message)=={'ack':'ACK'}
    assert not run.runtime.journal.pending_ids('a') and run.runtime.state().document()['active_trade'] is None


def test_offer_cannot_bypass_the_active_native_query(ui):
    _,_,command,evidence=opened(ui);assert grant(ui,command,evidence)
    _,controller,_,event=ui
    payload={'token_hex':'AABBCCDD','query_generation':7,'slot':0,'snapshot':event['payload']['checkpoint']['party']}
    controller.offer('a',payload)
    for field,value in [('token_hex','11223344'),('slot',1),('query_generation',6)]:
        with pytest.raises(JournalError):controller.offer('a',{**payload,field:value})
