"""Controlled original starter scripts feed the production settlement dispatcher."""
import json
import os
import secrets
import tempfile
from pathlib import Path

import pytest

from server.gen1_initial_observation import display_name
from server.gen1_run_config import create_runtime
from server.gen1_starter_settlement import COMPONENT, starter_flag
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL
from tests.unit.test_gen1_initial_observation import send
from tests.unit.test_gen1_inventory_observation import deliver as inventory_event, party_point
from tests.unit.test_gen1_engine_signal_runtime import deliver as engine_event
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract
from server.gen1_party_codec import PartyCodec
from tools.run_gb_gate import run_gate

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,
    pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variants',[('red','blue'),('blue','yellow'),('yellow','yellow')])
def test_original_starter_scripts_settle_one_paired_link_without_server_roster_bootstrap(variants):
    directory=Path(tempfile.mkdtemp(prefix='starter-pair-',dir=ROOT/'.cache'))
    rows={}
    for player,variant in zip(('a','b'),variants,strict=True):
        spec=directory/(player+'-input.json');result=directory/(player+'-result.json')
        spec.write_text(json.dumps({'party_hex':party_point(variant,[make_blob(PartyCodec(variant))])['fields']['party'],
            'complete_starter':True,'only_starter':True,'context_generation':player*32,
            'species':84 if variant=='yellow' else 153}))
        passed,path,log=run_gate('lua/tests/test_gen1_engine_signals_gate.lua',rom_key=variant,quiet=True,timeout=130,
            extra_env={'SLINK_SIGNAL_INPUT':str(spec),'SLINK_SIGNAL_RESULT':str(result)})
        assert passed,f'{path}\n{log[-5000:]}'
        document=json.loads(result.read_text());assert document['passed'] and len(document['cases'])==1
        row=document['cases'][0];assert row['unchanged']
        assert not starter_flag(row['initial_point']) and starter_flag(row['final_point'])
        rows[player]=row
    runtime=create_runtime(directory/'run',contract(*variants));owners={};initials={};initial_ops={}
    try:
        for player,row in rows.items():
            point=row['signals'][0]['point'];nonce=secrets.token_hex(16);owners[player]=object()
            metadata={'schema':METADATA_SCHEMA,'cartridge':runtime.contract['players'][player],
                'save_identity':{'ot_id':point['player_id_hex'],'trainer_name':display_name(bytes.fromhex(point['trainer_hex']))},
                'physical_instance':('1' if player=='a' else '2')*32}
            runtime.process({'protocol':PROTOCOL,'run_id':runtime.journal.run_id,'player':player,'event':'hello','seq':0,
                'client_nonce':nonce,'operation_id':nonce,'context_generation':player*32,'gen1_metadata':metadata},owners[player])
            initials[player]={'schema':'rby-initial-observation-v1','context_generation':player*32,
                'final_sha1':runtime.contract['players'][player]['final_rom_sha1'],'frame':row['initial_frame'],
                'host':{'owner_id':metadata['physical_instance'],'process_id':123 if player=='a' else 456,
                    'capability_id':'bizhawk-2.11.1-gambatte-exclusive-hold-v1','held':True},'source':row['initial_point']}
            initial_ops[player]=secrets.token_hex(16)
            send(runtime,player,owners[player],initials[player],initial_ops[player])
        assert not runtime.state().identities.document()['members']
        for player,row in rows.items():
            for event in row['events']:
                engine_event(runtime,player,owners[player],event['payload']['payload'],event['operation_id'])
            checkpoint={**initials[player],'frame':row['final_frame'],'source':row['final_point']}
            inventory_event(runtime,player,owners[player],{'sequence':1,'previous_operation_id':initial_ops[player],
                'observation':checkpoint})
        state=runtime.state();assert len(state.rules.links)==1 and len(state.identities.document()['members'])==2
        assert len(state.identities.document()['links'])==1
        for player,row in rows.items():
            blob=state.document()['components'][COMPONENT]['settled'][player]['blob_hex']
            if runtime.contract['players'][player]['variant']=='yellow':assert bytes.fromhex(blob)[7]==0xA3
        assert state.barrier.ticket() is None and not any(state.rules.pokeballs_obtained.values())
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
    finally:runtime.close()
