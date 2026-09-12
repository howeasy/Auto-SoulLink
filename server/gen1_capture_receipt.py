"""Validate one source-qualified successful wild capture delivered to the party or current box.

Evidence is two complete physical witnesses at the pinned delivery call and its return
inside ItemUseBall. A success flag, a count change or a mon's absence proves nothing by
itself; the appended/inserted record must be the enemy battle struct exactly as
_AddPartyMon or SendNewMonToBox copies it, with every other member untouched.
Nothing here infers Soul Link membership, clauses, ball credit or history.
"""
import json
from pathlib import Path

from server.gen1_engine_signals import integer, raw
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol_journal import JournalError

DATA=json.loads((Path(__file__).resolve().parents[1]/'data/games/gen1_rby/capture_sites.json').read_text())
SCHEMA='rby-capture-receipt-v1'
FIELDS={'party_hex','box_hex','enemy_hex','trainer_hex','player_id_hex','map_id','battle_flag','battle_type',
        'cur_species','captured_species','cur_level','mon_location','current_box'}
CONTEXT=('trainer_hex','player_id_hex','map_id','battle_flag','battle_type','cur_species','captured_species','cur_level','current_box')


def party_mons(codec, party):
    count=party[0]
    if count>6 or party[count+1]!=255:raise JournalError('invalid capture party list')
    mons=[]
    for slot in range(count):
        blob=party[8+44*slot:52+44*slot]+party[272+11*slot:283+11*slot]+party[338+11*slot:349+11*slot]
        mon=codec.validate_blob(blob)
        if mon.species_index!=party[slot+1]:raise JournalError('capture party species list differs')
        mons.append(mon)
    return mons


def box_records(codec, box):
    """Exact 33+11+11 byte records of the current box; keys use the shared physical formula."""
    count=box[0]
    if count>20 or box[count+1]!=255:raise JournalError('invalid capture box list')
    records=[]
    for slot in range(count):
        mon=box[22+33*slot:55+33*slot];ot=box[682+11*slot:693+11*slot];nick=box[902+11*slot:913+11*slot]
        if mon[0]!=box[slot+1] or str(mon[0]) not in codec.profile['species']:raise JournalError('invalid capture boxed species')
        codec._ot_name(ot,'boxed OT');codec._name(nick,'boxed nickname')
        records.append((mon+ot+nick,f'{mon[27:29].hex().upper()}:{mon[12:14].hex().upper()}:{mon[0]:02X}'))
    return records


def witness(signal, kind, variant, identity):
    if not isinstance(signal,dict) or set(signal)!={'kind','frame','pc','bank','sp','point'} or signal['kind']!=kind:
        raise JournalError('complete capture witness required')
    profile=DATA['titles'][variant];site=profile['sites'][kind]
    if (type(signal['pc']) is not int or signal['pc']!=site['address'] or
            type(signal['bank']) is not int or signal['bank']!=site['bank']):
        raise JournalError('capture witness source differs')
    integer(signal['frame'],0,2**53-1,'frame');integer(signal['sp'],0xC000,0xDFFF,'stack')
    point=signal['point']
    if not isinstance(point,dict) or set(point)!=FIELDS:raise JournalError('complete capture evidence required')
    for field in ('map_id','battle_flag','battle_type','cur_species','captured_species','cur_level','mon_location','current_box'):
        integer(point[field],0,255,field)
    codec=PartyCodec(variant);name=raw(point['trainer_hex'],11);codec._name(name,'capture save name')
    player=raw(point['player_id_hex'],2)
    if identity!={'ot_id':point['player_id_hex'],'trainer_name':display_name(name)}:
        raise JournalError('capture witness belongs to another save')
    party=raw(point['party_hex'],404);box=raw(point['box_hex'],1122);enemy=raw(point['enemy_hex'],29)
    mons=party_mons(codec,party);records=box_records(codec,box)
    keys=[mon.key for mon in mons]+[key for _,key in records]
    if len(set(keys))!=len(keys):raise JournalError('capture witness roster has a duplicate physical key')
    if point['battle_flag']!=profile['wild_battle_flag'] or point['battle_type'] not in profile['delivering_battle_types'].values():
        raise JournalError('capture witness is not a delivering wild battle')
    if point['current_box']&127>=12:raise JournalError('invalid capture current box')
    return {'codec':codec,'party':party,'mons':mons,'box':box,'records':records,'keys':set(keys),'enemy':enemy,
            'name':name,'player':player,'point':point,'frame':signal['frame'],'sp':signal['sp']}


def _decode_capture(receipt, variant, identity):
    if not isinstance(receipt,dict) or set(receipt)!={'destination','begin','end'} or receipt['destination'] not in ('party','box'):
        raise JournalError('complete capture receipt required')
    where=receipt['destination']
    a=witness(receipt['begin'],where+'_begin',variant,identity);b=witness(receipt['end'],where+'_end',variant,identity)
    if b['frame']<a['frame'] or a['sp']!=b['sp']:raise JournalError('capture return does not continue its call')
    before,after=a['point'],b['point']
    if any(before[field]!=after[field] for field in CONTEXT):raise JournalError('capture context changed between call and return')
    enemy=a['enemy']
    # SendNewMonToBox writes wEnemyMonBoxLevel (offset 3); nothing else in the struct may move.
    if b['enemy'][:3]+b['enemy'][4:]!=enemy[:3]+enemy[4:]:raise JournalError('enemy battle struct changed during delivery')
    species,level=enemy[0],enemy[14]
    codec=a['codec'];facts=codec.profile['species'].get(str(species))
    if facts is None or list(enemy[5:7])!=facts['types']:raise JournalError('enemy battle struct species/types are not canonical')
    if not (before['cur_species']==before['captured_species']==species) or before['cur_level']!=level:
        raise JournalError('caught species/level differ from the enemy battle struct')
    if int.from_bytes(enemy[1:3],'big')<1 or not 1<=level<=100:raise JournalError('a delivered capture needs HP and a legal level')
    experience=codec.experience_for_level(facts['growth_rate'],level)
    if b['enemy'][3]!=(enemy[3] if where=='party' else level):
        raise JournalError('enemy box level differs from the delivery routine')
    # Validate the enemy's complete typed data even for a boxed delivery, whose
    # 33-byte record has no cached-stat tail of its own.
    probe=bytearray(66);probe[:12]=enemy[:12];probe[3]=0;probe[12:14]=a['player']
    probe[14:17]=experience.to_bytes(3,'big');probe[27:29]=enemy[12:14];probe[29:33]=enemy[25:29]
    probe[33]=level;probe[34:44]=enemy[15:25];probe[44:55]=probe[55:66]=a['name']
    if codec.validate_blob(bytes(probe)).pp_ups!=(0,0,0,0):raise JournalError('wild capture enemy has PP Ups')
    if where=='party':
        count=a['party'][0]
        if count>5 or before['mon_location']!=0:raise JournalError('party capture call requires an open slot and the player party destination')
        if b['party'][0]!=count+1 or b['box']!=a['box']:raise JournalError('party capture did not append exactly one member')
        if (b['party'][1:1+count]!=a['party'][1:1+count] or b['party'][8:8+44*count]!=a['party'][8:8+44*count] or
                b['party'][272:272+11*count]!=a['party'][272:272+11*count] or b['party'][338:338+11*count]!=a['party'][338:338+11*count]):
            raise JournalError('party capture disturbed existing members')
        mon=b['mons'][count];blob=mon.raw
        if (blob[0]!=species or blob[1:3]!=enemy[1:3] or blob[3]!=0 or blob[4:12]!=enemy[4:12] or blob[12:14]!=a['player'] or
                mon.experience!=experience or blob[17:27]!=bytes(10) or blob[27:29]!=enemy[12:14] or mon.pp_ups!=(0,0,0,0) or
                blob[29:33]!=bytes(codec.max_pp(move,0) if move else 0 for move in blob[8:12]) or
                blob[33]!=level or blob[34:44]!=enemy[15:25] or blob[44:55]!=a['name']):
            raise JournalError('appended party member is not the enemy battle struct delivered by _AddPartyMon')
        key=mon.key;record=blob;location={'kind':'party','slot':count,'box':None}
    else:
        count=a['box'][0]
        if a['party'][0]!=6 or count>19:raise JournalError('box capture call requires a full party and an open box slot')
        if b['party']!=a['party'] or b['box'][0]!=count+1:raise JournalError('box capture did not insert exactly one member')
        if (b['box'][2:2+count]!=a['box'][1:1+count] or b['box'][55:55+33*count]!=a['box'][22:22+33*count] or
                b['box'][693:693+11*count]!=a['box'][682:682+11*count] or b['box'][913:913+11*count]!=a['box'][902:902+11*count]):
            raise JournalError('box capture did not shift existing members down by one')
        record,key=b['records'][0];mon,ot=record[:33],record[33:44]
        catch=DATA['titles'][variant]['boxed_catch_rate_overrides'].get(str(species),enemy[7])
        if (mon[0:3]!=enemy[0:3] or mon[3]!=level or mon[4:7]!=enemy[4:7] or mon[8:12]!=enemy[8:12] or mon[12:14]!=a['player'] or
                mon[7]!=catch or
                int.from_bytes(mon[14:17],'big')!=experience or mon[17:27]!=bytes(10) or mon[27:29]!=enemy[12:14] or
                mon[29:33]!=enemy[25:29] or ot!=a['name']):
            raise JournalError('inserted box member is not the enemy battle struct delivered by SendNewMonToBox')
        location={'kind':'box','slot':0,'box':before['current_box']&127}
    if key in a['keys']:raise JournalError('captured key collides with an already owned physical key')
    return {'kind':'capture','destination':where,'key':key,'blob_hex':record.hex().upper(),'location':location,
            'species_index':species,'level':level,'map_id':before['map_id'],'battle_type':before['battle_type'],
            'call_frame':a['frame'],'return_frame':b['frame']}


def decode_capture(receipt,variant,identity):
    if not isinstance(variant,str) or variant not in DATA['titles']:raise JournalError('RBY capture variant required')
    try:return _decode_capture(receipt,variant,identity)
    except PartyCodecError as error:raise JournalError(str(error)) from error


def validate_receipt(payload, metadata):
    if not isinstance(payload,dict) or set(payload)!={'schema','source_sha256','variant','context_generation','final_sha1','receipt'}:
        raise JournalError('complete capture receipt payload required')
    cartridge=metadata['gen1_metadata']['cartridge']
    if (payload['schema']!=SCHEMA or payload['source_sha256']!=DATA['sha256'] or payload['variant']!=cartridge['variant'] or
            payload['context_generation']!=metadata['control_binding']['context_generation'] or payload['final_sha1']!=cartridge['final_rom_sha1']):
        raise JournalError('capture receipt differs from admission/source')
    return decode_capture(payload['receipt'],payload['variant'],metadata['save_identity'])
