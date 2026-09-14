import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from server.gen1_engine_signals import DATA, validate_signal, validate_batch
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_inventory_observation import party_point

ROOT=Path(__file__).resolve().parents[2]
SAVE={'ot_id':'1234','trainer_name':'SAME'}


def signal(variant,kind='battle_faint'):
    blob=bytearray(make_blob(PartyCodec(variant)))
    if kind.endswith('faint'):blob[1:3]=b'\0\0'
    if kind=='poison_faint':blob[4]=8
    site=DATA['titles'][variant]['sites'][kind]
    party=party_point(variant,[] if kind=='starter_begin' else [bytes(blob)])['fields']['party']
    return {'kind':kind,'frame':100,'pc':site['address'],'bank':site['bank'],'sp':0xDFFE,
        'point':{'party_hex':party,'trainer_hex':'92808C8450000000000000','player_id_hex':'1234',
            'map_id':DATA['titles'][variant]['starter_map'],'battle_flag':1 if kind=='battle_faint' else 0,
            'active_slot':0,'battle_hp':0,'battle_species':153,'which':0,'mon_location':0,'cur_species':153,'cur_level':5}}


@pytest.mark.parametrize('variant',['red','blue','yellow'])
@pytest.mark.parametrize('kind',['battle_faint','poison_faint','starter_begin','starter_end'])
def test_exact_source_signals_identify_participant_and_grant_phase(variant,kind):
    result=validate_signal(signal(variant,kind),variant,SAVE)
    assert result['kind']==('faint' if kind.endswith('faint') else kind)
    if kind.endswith('faint'):assert result['key']==PartyCodec(variant).validate_blob(make_blob(PartyCodec(variant))).key


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_transformed_battle_species_does_not_change_original_identity(variant):
    value=signal(variant);value['point']['battle_species']=84
    assert validate_signal(value,variant,SAVE)['key'].endswith(':99')


@pytest.mark.parametrize('fault',['frame','pc','bank','stack','party','identity','hp','slot','battle','source','extra'])
def test_malformed_faint_evidence_is_refused(fault):
    value=signal('yellow')
    if fault=='frame':value['frame']=True
    elif fault=='pc':value['pc']+=1
    elif fault=='bank':value['bank']+=1
    elif fault=='stack':value['sp']=0x8000
    elif fault=='party':value['point']['party_hex']='FF'*404
    elif fault=='identity':value['point']['player_id_hex']='5678'
    elif fault=='hp':value['point']['battle_hp']=1
    elif fault=='slot':value['point']['active_slot']=1
    elif fault=='battle':value['point']['battle_flag']=0
    elif fault=='source':value['kind']='unknown'
    else:value['permission']='run'
    with pytest.raises((JournalError,ValueError)):validate_signal(value,'yellow',SAVE)


def test_poison_requires_hp_zero_and_still_poisoned_at_the_preclear_site():
    value=signal('yellow','poison_faint');party=bytearray.fromhex(value['point']['party_hex'])
    party[12]=0;value['point']['party_hex']=party.hex().upper()
    with pytest.raises(JournalError,match='poison'):validate_signal(value,'yellow',SAVE)


def test_batch_checks_admission_order_and_capacity():
    from tests.unit.test_gen1_sessions import contract
    metadata={'gen1_metadata':{'cartridge':contract('yellow','yellow')['players']['a']},
              'save_identity':SAVE,'control_binding':{'context_generation':'a'*32}}
    payload={'schema':'rby-engine-signals-v1','source_sha256':DATA['sha256'],'variant':'yellow',
        'context_generation':'a'*32,'final_sha1':metadata['gen1_metadata']['cartridge']['final_rom_sha1'],
        'sequence':1,'signals':[signal('yellow')]}
    assert len(validate_batch(payload,metadata))==1
    for field,value in [('source_sha256','f'*64),('sequence',True),('context_generation','b'*32),('signals',[]),
                        ('signals',[signal('yellow')]*33)]:
        bad=copy.deepcopy(payload);bad[field]=value
        with pytest.raises(JournalError):validate_batch(bad,metadata)
    bad=copy.deepcopy(payload);bad['signals'].append(signal('yellow'));bad['signals'][1]['frame']=99
    with pytest.raises(JournalError):validate_batch(bad,metadata)


def test_generated_signal_artifacts_match_pinned_source_and_original_rom_bytes():
    subprocess.run([sys.executable,str(ROOT/'tools/gen_gen1_engine_signals.py'),'--check'],cwd=ROOT,check=True)
    assert json.loads((ROOT/'data/games/gen1_rby/engine_signals.json').read_text())==DATA


def witness(variant,**overrides):
    site=DATA['titles'][variant]['sites']['save_witness']
    value={'kind':'save_witness','frame':100,'pc':site['address']+site['capture_offset'],'bank':site['bank'],'sp':0xDFFE,
        'point':{'digest':'a'*64,'projection':'cartram-0498-8000-v1','save_file_status':2}}
    value['point'].update(overrides);return value


@pytest.mark.parametrize('variant',['red','blue'])
def test_save_witness_site_is_the_start_menu_save_completion(variant):
    # pokered 405b624 engine/menus/save.asm:165-166 — SaveMenu.save: call SaveGameData ; hlcoord 1,13.
    site=DATA['titles'][variant]['sites']['save_witness']
    assert site=={'address':0x772D,'bank':0x1C,'capture_offset':3,'expected_hex':'CD487821A5C4','rom_offset':0x7372D,'symbol':'SaveMenu.save'}
    assert validate_signal(witness(variant),variant,SAVE)=={'kind':'save_witness','digest':'a'*64,'projection':'cartram-0498-8000-v1'}


@pytest.mark.parametrize('fault',['short_digest','lowercase_digest','status','projection','extra','pc'])
def test_save_witness_refuses_partial_or_foreign_saves(fault):
    value=witness('red')
    if fault=='short_digest':value['point']['digest']='a'*63
    elif fault=='lowercase_digest':value['point']['digest']='A'*64
    elif fault=='status':value['point']['save_file_status']=1
    elif fault=='projection':value['point']['projection']='cartram-0000-8000-v1'
    elif fault=='extra':value['point']['frame']=1
    else:value['pc']-=3
    with pytest.raises(JournalError):validate_signal(value,'red',SAVE)
