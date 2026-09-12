import copy
import secrets
from itertools import product

import pytest

from server.gen1_engine_signal_runtime import COMPONENT, interpret, key
from server.gen1_engine_signals import DATA
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol_journal import JournalError
from tests.unit.test_gen1_engine_signals import signal
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract


def payload(runtime,player,kinds,sequence=1):
    variant=runtime.contract['players'][player]['variant']
    signals=[signal(variant,kind) for kind in kinds]
    for row in signals:
        row['point']['player_id_hex']='0000'
        if row['kind']=='starter_end':
            party=bytearray.fromhex(row['point']['party_hex']);party[20:22]=b'\0\0'
            row['point']['party_hex']=party.hex().upper()
        row['frame']+=sequence
    return {'schema':'rby-engine-signals-v1','source_sha256':DATA['sha256'],'variant':variant,
        'context_generation':player*32,'final_sha1':runtime.contract['players'][player]['final_rom_sha1'],
        'sequence':sequence,'signals':signals}


def deliver(runtime,player,owner,value,operation=None):
    session=runtime.gate.sessions[player]
    return runtime.process({'protocol':runtime.protocol,'player':player,'session_id':session.session_id,
        'admission_epoch':runtime.gate.epoch,'seq':session.last_seq+1,'event':'engine_signals',
        'operation_id':operation or secrets.token_hex(16),'payload':value},owner)


@pytest.mark.parametrize('variants',list(product(('red','blue','yellow'),repeat=2)))
def test_owned_source_batches_commit_and_replay_without_inventing_rule_history(tmp_path,variants):
    runtime=create_runtime(tmp_path,contract(*variants))
    try:
        for player in ('a','b'):
            owner=admit(runtime,player);send(runtime,player,owner,observation(runtime,player))
            op=secrets.token_hex(16);value=payload(runtime,player,['battle_faint','poison_faint'])
            deliver(runtime,player,owner,value,op);before=runtime.journal.snapshot()
            deliver(runtime,player,owner,value,op);assert runtime.journal.snapshot()==before
            entry=runtime.state().document()['components'][COMPONENT][player]
            assert [row['cause'] for row in entry['transactions']]==['battle','poison']
            assert runtime.journal.record(COMPONENT,key(player)).value==entry
        state=runtime.state().document()
        assert not state['identities']['members'] and not state['rules']['core']['links']
        assert runtime.state().barrier.ticket() is None
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
    finally:runtime.close()
    runtime=open_runtime(tmp_path)
    try:assert runtime.state().document()['components'][COMPONENT]==state['components'][COMPONENT]
    finally:runtime.close()


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_starter_call_and_return_across_batches_form_one_source_transaction(tmp_path,variant):
    runtime=create_runtime(tmp_path,contract(variant,variant))
    try:
        owner=admit(runtime,'a');send(runtime,'a',owner,observation(runtime,'a'))
        deliver(runtime,'a',owner,payload(runtime,'a',['starter_begin']))
        entry=runtime.state().document()['components'][COMPONENT]['a']
        assert entry['pending_starter'] is not None and entry['transactions']==[]
        deliver(runtime,'a',owner,payload(runtime,'a',['starter_end'],2))
        entry=runtime.state().document()['components'][COMPONENT]['a']
        assert entry['pending_starter'] is None and len(entry['transactions'])==1
        assert entry['transactions'][0]['source_id']=='grant:starter:0'
        assert not runtime.state().identities.document()['members']
    finally:runtime.close()


@pytest.mark.parametrize('fault',['sequence','rewind','return_only','overlap','stack','species','corrupt_record'])
def test_sequence_and_unpaired_source_faults_leave_no_partial_semantics(tmp_path,fault):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owner=admit(runtime,'a');send(runtime,'a',owner,observation(runtime,'a'))
        value=payload(runtime,'a',['starter_begin','starter_end'])
        if fault=='sequence':value['sequence']=2
        elif fault=='rewind':value['signals'][0]['frame']=99
        elif fault=='return_only':value['signals']=value['signals'][1:]
        elif fault=='overlap':value['signals']=[value['signals'][0]]*2
        elif fault=='stack':value['signals'][1]['sp']-=2
        elif fault=='species':value['signals'][0]['point']['cur_species']=84
        else:
            deliver(runtime,'a',owner,value)
            state=runtime.state().document();state['components'][COMPONENT]['a']['transactions']=[]
            with pytest.raises(JournalError):Gen1RuntimeState.restore(state,data_dir=tmp_path)
            return
        before=runtime.journal.snapshot()
        with pytest.raises(JournalError):deliver(runtime,'a',owner,value)
        assert runtime.journal.snapshot()==before
    finally:runtime.close()
