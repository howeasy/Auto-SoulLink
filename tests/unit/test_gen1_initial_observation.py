import copy
import secrets
from itertools import product

import pytest

from server.gen1_full_save import SYMBOLS, layout
from server.gen1_initial_observation import COMPONENT, inventory
from server.gen1_launcher import OBSERVATION_FILES, configuration
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL
from server.protocol_journal import JournalError
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_party_codec import make_blob
from server.gen1_party_codec import PartyCodec
from server.gen1_runtime_state import Gen1RuntimeState


def source(variant,*,occupied=False):
    fields={name:bytearray(region['length']) for name,region in layout(variant)['regions'].items()}
    fields['name'][:]=bytes.fromhex('92808C8450000000000000') # SAME
    fields['party'][1]=255;fields['box'][1]=255
    if occupied:
        raw=make_blob(PartyCodec(variant),dv=0x1234,otid=0x9999)
        fields['party'][0:3]=bytes((1,raw[0],255));fields['party'][8:52]=raw[:44]
        fields['party'][272:283]=raw[44:55];fields['party'][338:349]=raw[55:]
    return {'schema':'rby-full-save-point-v1','variant':variant,'save_status':0,'cart_hex':'FF'*0x8000,
            'fields':{name:raw.hex().upper() for name,raw in fields.items()}}


def admit(runtime,player):
    nonce=secrets.token_hex(16);owner=object()
    packet={'protocol':PROTOCOL,'run_id':runtime.journal.run_id,'player':player,'event':'hello','seq':0,
            'client_nonce':nonce,'operation_id':nonce,'context_generation':player*32,
            'gen1_metadata':{'schema':METADATA_SCHEMA,'cartridge':runtime.contract['players'][player],
                'save_identity':{'ot_id':'0000','trainer_name':'SAME'},'physical_instance':('1' if player=='a' else '2')*32}}
    runtime.process(packet,owner)
    return owner


def send(runtime,player,owner,payload,operation=None):
    session=runtime.gate.sessions[player]
    message={'protocol':PROTOCOL,'player':player,'admission_epoch':runtime.gate.epoch,'session_id':session.session_id,
             'seq':session.last_seq+1,'operation_id':operation or secrets.token_hex(16),'event':'initial_observation','payload':payload}
    return runtime.process(message,owner)


def observation(runtime,player,*,occupied=False):
    return {'schema':'rby-initial-observation-v1','context_generation':player*32,
            'final_sha1':runtime.contract['players'][player]['final_rom_sha1'],'frame':100,
            'host':{'owner_id':('1' if player=='a' else '2')*32,'process_id':123 if player=='a' else 456,
                    'capability_id':'bizhawk-2.11.1-gambatte-exclusive-hold-v1','held':True},
            'source':source(runtime.contract['players'][player]['variant'],occupied=occupied)}


@pytest.mark.parametrize('variants',list(product(('red','blue','yellow'),repeat=2)))
def test_empty_run_enrollment_binds_context_without_capture_link_or_gameplay(tmp_path,variants):
    runtime=create_runtime(tmp_path,contract(*variants))
    try:
        for p in ('a','b'):
            owner=admit(runtime,p);send(runtime,p,owner,observation(runtime,p,occupied=p=='b'))
        state=runtime.state().document()
        assert not state['rules']['core']['links'] and not state['identities']['members']
        assert not any(state['rules']['runtime']['party_keys'].values())
        assert not any(state['rules']['core']['pokeballs_obtained'].values())
        assert state['components'][COMPONENT]['a']['inventory']['party_count']==0
        assert state['components'][COMPONENT]['b']['inventory']['party_count']==1
        assert set(state['identities']['contexts'])=={'a','b'} and runtime.state().barrier.ticket() is None
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
        assert set(OBSERVATION_FILES)<={row['path'] for row in configuration(runtime,'a')['files']}
        saved=state
    finally:runtime.close()
    reopened=open_runtime(tmp_path)
    try:assert reopened.state().document()['components'][COMPONENT]==saved['components'][COMPONENT]
    finally:reopened.close()


def test_enrollment_replay_is_idempotent_and_new_operation_cannot_replace_baseline(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owner=admit(runtime,'a');payload=observation(runtime,'a');operation=secrets.token_hex(16)
        send(runtime,'a',owner,payload,operation);before=runtime.journal.snapshot()
        send(runtime,'a',owner,payload,operation);assert runtime.journal.snapshot()==before
        with pytest.raises(JournalError):send(runtime,'a',owner,payload)
        assert runtime.journal.snapshot()==before
    finally:runtime.close()


@pytest.mark.parametrize('fault',['identity','variant','context','held','party','current_box','source_field'])
def test_invalid_initial_evidence_has_zero_committed_effect(tmp_path,fault):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owner=admit(runtime,'a');payload=observation(runtime,'a');before=runtime.journal.snapshot()
        if fault=='identity':payload['source']['fields']['name']='9184835000000000000000'
        elif fault=='variant':payload['source']['variant']='red'
        elif fault=='context':payload['context_generation']='f'*32
        elif fault=='held':payload['host']['held']=False
        elif fault=='party':payload['source']['fields']['party']='07'+'00'*403
        elif fault=='source_field':del payload['source']['fields']['sprites']
        else:
            syms=SYMBOLS['pokeyellow'];main=bytearray.fromhex(payload['source']['fields']['main'])
            main[syms['wCurrentBoxNum']-syms['wMainDataStart']]=12;payload['source']['fields']['main']=main.hex().upper()
        with pytest.raises((JournalError,ValueError)):send(runtime,'a',owner,payload)
        assert runtime.journal.snapshot()==before
    finally:runtime.close()


def test_active_box_is_read_from_wram_and_duplicate_party_box_keys_are_refused():
    point=source('yellow',occupied=True);raw=bytearray.fromhex(point['fields']['party'])
    box=bytearray(1122);box[0:3]=bytes((1,raw[8],255));box[22:55]=raw[8:41]
    box[682:693]=raw[272:283];box[902:913]=raw[338:349];point['fields']['box']=box.hex().upper()
    with pytest.raises(JournalError,match='duplicate'):inventory(point,{'ot_id':'0000','trainer_name':'SAME'})


def test_fresh_creation_cannot_shadow_a_legacy_or_existing_run(tmp_path):
    marker=tmp_path/'links.json';marker.write_text('existing')
    with pytest.raises(JournalError):create_runtime(tmp_path,contract())
    assert marker.read_text()=='existing' and not (tmp_path/'runtime.sqlite3').exists()


@pytest.mark.parametrize('fault',['inventory','metadata','binding','context_history','blocker'])
def test_corrupt_initial_record_refuses_read_only_restore(tmp_path,fault):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owner=admit(runtime,'a');send(runtime,'a',owner,observation(runtime,'a'))
        state=runtime.state().document();entry=state['components'][COMPONENT]['a']
        if fault=='inventory':entry['inventory']['party_count']=1
        elif fault=='metadata':entry['metadata']['scope']='physical_permission'
        elif fault=='binding':entry['binding']['binding_digest']='f'*64
        elif fault=='context_history':state['identities']['context_history']['a']=[]
        else:state['components']['gen1-runtime']['recovery']['blockers']={}
        with pytest.raises((JournalError,ValueError)):Gen1RuntimeState.restore(state,data_dir=tmp_path)
    finally:runtime.close()


def test_display_identity_matches_existing_client_decoder_for_every_allowed_name_byte():
    from lupa.lua54 import LuaRuntime
    from pathlib import Path
    from server.gen1_initial_observation import display_name
    text=(Path(__file__).resolve().parents[2]/'lua/memory_gb.lua').read_text()
    block=text[text.index('M._CHARSET = {'):text.index('\nfunction M.decodeString')]
    lua=LuaRuntime(unpack_returned_tuples=True);table=lua.execute('local M={}\n'+block+'\nreturn M._CHARSET')
    for value in PartyCodec('yellow').names:
        assert display_name(bytes((value,0x50)))==(table[value] or '?')
