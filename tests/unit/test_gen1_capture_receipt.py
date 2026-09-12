"""Capture delivery receipts: exact before/after physical evidence, hostile variants and pinned sites."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server.gen1_capture_receipt import DATA, SCHEMA, decode_capture, validate_receipt
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_gen1_party_codec import make_blob

ROOT=Path(__file__).resolve().parents[2]
SAVE={'ot_id':'1234','trainer_name':'SAME'}
NAME=bytes.fromhex('92808C8450000000000000')  # SAME; the cartridge copies all 11 bytes of wPlayerName
PLAYER=bytes.fromhex('1234')
NICK=bytes((0x85,0x88,0x92,0x87,0x50,0x52,0,0xFF,6,7,8))
ENEMY_KEYS={'species','level','dv','hp','status'}


def enemy_struct(codec,species=0x54,level=7,dv=0xABCD,hp=9,status=0):
    """wEnemyMon battle struct after ItemUseBall reloaded it with the original DVs."""
    facts=codec.profile['species'][str(species)]
    stats=b''.join(value.to_bytes(2,'big') for value in (20,11,12,13,14))
    return bytes((species,*hp.to_bytes(2,'big'),0,status,*facts['types'],45,1,2,0,0,*dv.to_bytes(2,'big'),level))+stats+bytes(
        (codec.max_pp(1,0),codec.max_pp(2,0)-1,0,0))  # the wild mon used a move; the party copy gets full PP


def party_blob(codec,enemy):
    """What _AddPartyMon writes for a wild capture: enemy HP/status/DVs/stats, fresh PP/exp, player OT."""
    species,level=enemy[0],enemy[14];facts=codec.profile['species'][str(species)]
    raw=bytearray(66);raw[0:3]=enemy[0:3];raw[4:12]=enemy[4:12];raw[12:14]=PLAYER
    raw[14:17]=codec.experience_for_level(facts['growth_rate'],level).to_bytes(3,'big');raw[27:29]=enemy[12:14]
    raw[29:33]=bytes((codec.max_pp(1,0),codec.max_pp(2,0),0,0));raw[33]=level;raw[34:44]=enemy[15:25];raw[44:55]=NAME;raw[55:66]=NICK
    return bytes(raw)


def box_record(codec,enemy):
    """What SendNewMonToBox writes into slot 0: first 12 enemy bytes with the level as box level, then exp/DVs/PP."""
    species,level=enemy[0],enemy[14];facts=codec.profile['species'][str(species)]
    raw=bytearray(33);raw[0:12]=enemy[0:12];raw[3]=level;raw[12:14]=PLAYER
    raw[14:17]=codec.experience_for_level(facts['growth_rate'],level).to_bytes(3,'big');raw[27:29]=enemy[12:14];raw[29:33]=enemy[25:29]
    return bytes(raw)+NAME+NICK


def party_bytes(blobs):
    party=bytearray(404);party[0]=len(blobs);party[1+len(blobs)]=255
    for slot,raw in enumerate(blobs):
        party[1+slot]=raw[0];party[8+44*slot:52+44*slot]=raw[:44];party[272+11*slot:283+11*slot]=raw[44:55];party[338+11*slot:349+11*slot]=raw[55:]
    return bytes(party)


def box_bytes(records):
    box=bytearray(1122);box[0]=len(records);box[1+len(records)]=255
    for slot,raw in enumerate(records):
        box[1+slot]=raw[0];box[22+33*slot:55+33*slot]=raw[:33];box[682+11*slot:693+11*slot]=raw[33:44];box[902+11*slot:913+11*slot]=raw[44:]
    return bytes(box)


def owned(codec,count,start=0):
    return [make_blob(codec,dv=0x1000+index,otid=0x9999) for index in range(start,start+count)]


def point(party,box,enemy,**over):
    fields={'party_hex':party.hex().upper(),'box_hex':box.hex().upper(),'enemy_hex':enemy.hex().upper(),
            'trainer_hex':NAME.hex().upper(),'player_id_hex':'1234','map_id':33,'battle_flag':1,'battle_type':0,
            'cur_species':enemy[0],'captured_species':enemy[0],'cur_level':enemy[14],'mon_location':0,'current_box':3}
    fields.update(over);return fields


def signal(variant,kind,frame,value):
    site=DATA['titles'][variant]['sites'][kind]
    return {'kind':kind,'frame':frame,'pc':site['address'],'bank':site['bank'],'sp':0xDFF0,'point':value}


def receipt(variant='yellow',destination='party',party_count=2,box_count=0,**over):
    codec=PartyCodec(variant);enemy=enemy_struct(codec,**{k:v for k,v in over.items() if k in ENEMY_KEYS})
    extra={k:v for k,v in over.items() if k not in ENEMY_KEYS}
    party_before=owned(codec,6 if destination=='box' else party_count)
    box_before=[blob[:33]+blob[44:] for blob in owned(codec,box_count,start=10)]
    before=point(party_bytes(party_before),box_bytes(box_before),enemy,**extra)
    if destination=='box':
        shifted=enemy[:3]+bytes((enemy[14],))+enemy[4:]  # SendNewMonToBox writes wEnemyMonBoxLevel
        after=point(party_bytes(party_before),box_bytes([box_record(codec,enemy)]+box_before),shifted,**extra)
    else:
        after=point(party_bytes(party_before+[party_blob(codec,enemy)]),box_bytes(box_before),enemy,**extra)
    return {'destination':destination,'begin':signal(variant,destination+'_begin',100,before),'end':signal(variant,destination+'_end',160,after)}


def rewrite(value,witness,field,edit):
    raw=bytearray.fromhex(value[witness]['point'][field]);edit(raw);value[witness]['point'][field]=raw.hex().upper()


@pytest.mark.parametrize('variant',['red','blue','yellow'])
@pytest.mark.parametrize('destination,party_count,box_count',[('party',0,0),('party',5,20),('box',6,0),('box',6,19)])
def test_exact_delivery_identifies_key_blob_and_location(variant,destination,party_count,box_count):
    result=decode_capture(receipt(variant,destination,party_count,box_count),variant,SAVE)
    assert result['kind']=='capture' and result['key']=='ABCD:1234:54' and result['destination']==destination
    expected={'kind':'party','slot':party_count,'box':None} if destination=='party' else {'kind':'box','slot':0,'box':3}
    assert result['location']==expected and (result['species_index'],result['level'],result['map_id'])==(0x54,7,33)
    assert (result['call_frame'],result['return_frame'],result['battle_type'])==(100,160,0)
    blob=bytes.fromhex(result['blob_hex'])
    assert len(blob)==(66 if destination=='party' else 55) and blob[27:29]==b'\xab\xcd' and blob[12:14]==PLAYER


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_caught_species_comes_from_the_cartridge_struct_not_a_table(variant):
    codec=PartyCodec(variant)
    for species in sorted(int(key) for key in codec.profile['species'])[::23]:
        for destination in ('party','box'):
            result=decode_capture(receipt(variant,destination,species=species,level=41,dv=0x0102),variant,SAVE)
            assert result['species_index']==species and result['key']==f'0102:1234:{species:02X}'


def test_safari_ball_capture_and_status_ailment_are_delivered_facts():
    result=decode_capture(receipt(battle_type=2,status=8,hp=1),'yellow',SAVE)
    assert result['battle_type']==2 and bytes.fromhex(result['blob_hex'])[4]==8


FAULTS=['no_delivery','wrong_mon','disturbed','box_changed','trainer','old_man','pikachu','unassigned_type','pc','bank',
        'swapped','stack','frame','identity','not_captured','collision','mon_location','zero_hp','pp_ups','experience',
        'ot_name','enemy_changed','level','types','context','extra','missing','destination']


@pytest.mark.parametrize('fault',FAULTS)
def test_hostile_party_evidence_is_refused(fault):
    value=receipt()
    if fault=='no_delivery':value['end']['point']['party_hex']=value['begin']['point']['party_hex']
    elif fault=='wrong_mon':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(8+44*2+27,0x11))
    elif fault=='disturbed':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(10,0))  # slot 0 HP low byte 10 -> 0
    elif fault=='box_changed':value['end']['point']['box_hex']=box_bytes([box_record(PartyCodec('yellow'),bytes.fromhex(value['begin']['point']['enemy_hex']))]).hex().upper()
    elif fault=='trainer':value['begin']['point']['battle_flag']=value['end']['point']['battle_flag']=2
    elif fault=='old_man':value['begin']['point']['battle_type']=value['end']['point']['battle_type']=1
    elif fault=='pikachu':value['begin']['point']['battle_type']=value['end']['point']['battle_type']=4
    elif fault=='unassigned_type':value['begin']['point']['battle_type']=value['end']['point']['battle_type']=3
    elif fault=='pc':value['begin']['pc']+=1
    elif fault=='bank':value['end']['bank']+=1
    elif fault=='swapped':value['begin']=copy.deepcopy(value['end'])
    elif fault=='stack':value['end']['sp']-=2
    elif fault=='frame':value['end']['frame']=99
    elif fault=='identity':value['begin']['point']['player_id_hex']=value['end']['point']['player_id_hex']='5678'
    elif fault=='not_captured':value['begin']['point']['captured_species']=value['end']['point']['captured_species']=0
    elif fault=='collision':
        codec=PartyCodec('yellow');enemy=bytes.fromhex(value['begin']['point']['enemy_hex'])
        twin=make_blob(codec,species=0x54,otid=0x1234,dv=0xABCD)
        value['begin']['point']['party_hex']=party_bytes([twin]).hex().upper()
        value['end']['point']['party_hex']=party_bytes([twin,party_blob(codec,enemy)]).hex().upper()
    elif fault=='mon_location':value['begin']['point']['mon_location']=value['end']['point']['mon_location']=1
    elif fault=='zero_hp':value=receipt(hp=0)
    elif fault=='pp_ups':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(8+44*2+29,raw[8+44*2+29]|0xC0))
    elif fault=='experience':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(8+44*2+16,raw[8+44*2+16]+1))
    elif fault=='ot_name':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(272+11*2+5,1))
    elif fault=='enemy_changed':rewrite(value,'end','enemy_hex',lambda raw:raw.__setitem__(12,0x11))
    elif fault=='level':value['begin']['point']['cur_level']=value['end']['point']['cur_level']=8
    elif fault=='types':
        for witness in ('begin','end'):rewrite(value,witness,'enemy_hex',lambda raw:raw.__setitem__(5,raw[5]^1))
    elif fault=='context':value['end']['point']['map_id']=34
    elif fault=='extra':value['end']['point']['ball']=4
    elif fault=='missing':del value['begin']['point']['captured_species']
    else:value['destination']='daycare'
    with pytest.raises(JournalError):decode_capture(value,'yellow',SAVE)


@pytest.mark.parametrize('fault',['party_open','box_full','appended','wrong_pp','stale_box_level','ot_name','disturbed_party'])
def test_hostile_box_evidence_is_refused(fault):
    value=receipt(destination='box',box_count=2)
    codec=PartyCodec('yellow')
    if fault=='party_open':
        for witness in ('begin','end'):value[witness]['point']['party_hex']=party_bytes(owned(codec,5)).hex().upper()
    elif fault=='box_full':value=receipt(destination='box',box_count=20)
    elif fault=='appended':
        enemy=bytes.fromhex(value['begin']['point']['enemy_hex']);before=bytes.fromhex(value['begin']['point']['box_hex'])
        records=[before[22+33*s:55+33*s]+before[682+11*s:693+11*s]+before[902+11*s:913+11*s] for s in range(2)]
        value['end']['point']['box_hex']=box_bytes(records+[box_record(codec,enemy)]).hex().upper()
    elif fault=='wrong_pp':rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+30,raw[22+30]+1))
    elif fault=='stale_box_level':rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+3,0))
    elif fault=='ot_name':rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(682+3,0x50))  # "SAM": still a legal name
    else:rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(10,0))
    with pytest.raises(JournalError):decode_capture(value,'yellow',SAVE)


def test_receipt_payload_binds_to_admitted_source_context_and_cartridge():
    from tests.unit.test_gen1_sessions import contract
    metadata={'gen1_metadata':{'cartridge':contract('yellow','yellow')['players']['a']},'save_identity':SAVE,
              'control_binding':{'context_generation':'a'*32}}
    payload={'schema':SCHEMA,'source_sha256':DATA['sha256'],'variant':'yellow','context_generation':'a'*32,
             'final_sha1':metadata['gen1_metadata']['cartridge']['final_rom_sha1'],'receipt':receipt()}
    assert validate_receipt(payload,metadata)['kind']=='capture'
    for field,value in [('schema','x'),('source_sha256','f'*64),('variant','red'),('context_generation','b'*32),('final_sha1','0'*40)]:
        bad=copy.deepcopy(payload);bad[field]=value
        with pytest.raises(JournalError):validate_receipt(bad,metadata)
    bad=copy.deepcopy(payload);del bad['receipt']
    with pytest.raises(JournalError):validate_receipt(bad,metadata)


def test_generated_capture_sites_match_pinned_source_and_original_rom_bytes():
    subprocess.run([sys.executable,str(ROOT/'tools/gen_gen1_capture_sites.py'),'--check'],cwd=ROOT,check=True)
    assert json.loads((ROOT/'data/games/gen1_rby/capture_sites.json').read_text())==DATA
    for profile in DATA['titles'].values():
        assert profile['delivering_battle_types']=={'BATTLE_TYPE_NORMAL':0,'BATTLE_TYPE_SAFARI':2} and profile['wild_battle_flag']==1
        sites=profile['sites']
        assert sites['party_end']['address']==sites['party_begin']['address']+3 and sites['box_end']['address']==sites['box_begin']['address']+3
        assert sites['party_begin']['expected_hex'][:2]==sites['box_begin']['expected_hex'][:2]=='CD'


def test_lua_site_data_mirrors_the_json_artifact():
    from lupa import LuaRuntime
    value=LuaRuntime(unpack_returned_tuples=True).execute((ROOT/'data/games/gen1_rby/gen1_capture_sites.lua').read_text())
    assert value.sha256==DATA['sha256']
    for variant,profile in DATA['titles'].items():
        assert dict(value.titles[variant].addresses.items())==profile['addresses']
        for kind,site in profile['sites'].items():
            row=value.titles[variant].sites[kind]
            assert (row.address,row.bank,row.rom_offset,row.expected_hex)==(site['address'],site['bank'],site['rom_offset'],site['expected_hex'])


@pytest.mark.parametrize('fault',['moves','party_pp','party_catch','box_catch','enemy_box_level','enemy_boxed_move','enemy_boxed_stats'])
def test_delivery_rejects_legal_but_wrong_moves_pp_catch_and_enemy_drift(fault):
    where='box' if fault in {'box_catch','enemy_boxed_move','enemy_boxed_stats'} else 'party'
    value=receipt(destination=where)
    if fault=='moves':
        def change(raw):
            raw[8+44*2+8]=3
            raw[8+44*2+29]=PartyCodec('yellow').max_pp(3,0)
        rewrite(value,'end','party_hex',change)
    elif fault=='party_pp':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(8+44*2+29,raw[8+44*2+29]-1))
    elif fault=='party_catch':rewrite(value,'end','party_hex',lambda raw:raw.__setitem__(8+44*2+7,46))
    elif fault=='box_catch':rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+7,46))
    elif fault=='enemy_box_level':rewrite(value,'end','enemy_hex',lambda raw:raw.__setitem__(3,99))
    elif fault=='enemy_boxed_move':
        for which in ('begin','end'):rewrite(value,which,'enemy_hex',lambda raw:raw.__setitem__(8,255))
        rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+8,255))
    else:
        for which in ('begin','end'):rewrite(value,which,'enemy_hex',lambda raw:raw.__setitem__(slice(15,17),b'\0\1'))
    with pytest.raises(JournalError):decode_capture(value,'yellow',SAVE)


def test_yellow_boxed_kadabra_has_only_its_source_defined_catch_byte_override():
    value=receipt(destination='box',species=0x26)
    for which in ('begin','end'):rewrite(value,which,'enemy_hex',lambda raw:raw.__setitem__(7,100))
    rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+7,96))
    assert bytes.fromhex(decode_capture(value,'yellow',SAVE)['blob_hex'])[7]==96
    rewrite(value,'end','box_hex',lambda raw:raw.__setitem__(22+7,100))
    with pytest.raises(JournalError):decode_capture(value,'yellow',SAVE)
