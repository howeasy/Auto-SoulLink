"""Validate source-qualified engine evidence without inferring gameplay history."""
import json
import re
from pathlib import Path

from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError

DATA=json.loads((Path(__file__).resolve().parents[1]/'data/games/gen1_rby/engine_signals.json').read_text())
SCHEMA='rby-engine-signals-v1'


def integer(value, low, high, label):
    if type(value) is not int or not low<=value<=high:raise JournalError('invalid engine signal '+label)
    return value


def raw(value, length):
    if not isinstance(value,str) or not re.fullmatch('[0-9A-F]{'+str(length*2)+'}',value):
        raise JournalError('canonical engine signal bytes required')
    return bytes.fromhex(value)


def validate_signal(signal, variant, identity):
    if not isinstance(signal,dict) or set(signal)!={'kind','frame','pc','bank','sp','point'}:
        raise JournalError('complete engine signal required')
    profile=DATA['titles'][variant];kind=signal['kind']
    if not isinstance(kind,str) or kind not in profile['sites']:raise JournalError('unknown engine source')
    site=profile['sites'][kind]
    if (type(signal['pc']) is not int or signal['pc']!=site['address']+site.get('capture_offset',0) or
            type(signal['bank']) is not int or signal['bank']!=site['bank']):
        raise JournalError('engine signal source differs')
    integer(signal['frame'],0,2**53-1,'frame');integer(signal['sp'],0xC000,0xDFFF,'stack')
    point=signal['point']
    if kind=='bag_received':
        from server.gen1_bag import decode_bag, BALLS
        if not isinstance(point,dict) or set(point)!={'bag_hex','trainer_hex','player_id_hex','destination','flags','item','quantity'}:
            raise JournalError('complete bag delivery evidence required')
        integer(point['destination'],0,65535,'inventory destination');integer(point['flags'],0,255,'flags')
        integer(point['item'],1,254,'item');integer(point['quantity'],1,99,'quantity')
        name=raw(point['trainer_hex'],11);PartyCodec(variant)._name(name,'bag save name');raw(point['player_id_hex'],2)
        if identity!={'ot_id':point['player_id_hex'],'trainer_name':display_name(name)}:
            raise JournalError('bag delivery belongs to another save')
        rows=decode_bag(point['bag_hex'])
        if point['destination']!=profile['addresses']['wNumBagItems'] or not point['flags']&16 or point['item'] not in BALLS:
            raise JournalError('successful ball delivery to the bag required')
        if not any(row['item']==point['item'] and row['quantity']>=point['quantity'] for row in rows):
            # A delivery may split across multiple stacks at 99.
            if sum(row['quantity'] for row in rows if row['item']==point['item'])<point['quantity']:
                raise JournalError('delivered balls are absent from bag readback')
        return {'kind':'pokeballs_obtained','item':point['item'],'quantity':point['quantity']}
    if not isinstance(point,dict) or set(point)!={'party_hex','trainer_hex','player_id_hex','map_id','battle_flag',
            'active_slot','battle_hp','battle_species','which','mon_location','cur_species','cur_level'}:
        raise JournalError('complete engine observation required')
    for field in ('map_id','battle_flag','active_slot','battle_species','which','mon_location','cur_species','cur_level'):
        integer(point[field],0,255,field)
    integer(point['battle_hp'],0,65535,'battle HP')
    codec=PartyCodec(variant);name=raw(point['trainer_hex'],11);codec._name(name,'engine save name')
    raw(point['player_id_hex'],2)
    if identity!={'ot_id':point['player_id_hex'],'trainer_name':display_name(name)}:
        raise JournalError('engine signal belongs to another save')
    party=raw(point['party_hex'],404);count=party[0]
    if count>6 or party[count+1]!=255:raise JournalError('invalid engine party list')
    mons=[]
    for slot in range(count):
        blob=party[8+44*slot:52+44*slot]+party[272+11*slot:283+11*slot]+party[338+11*slot:349+11*slot]
        mon=codec.validate_blob(blob)
        if mon.species_index!=party[slot+1] or any(row.key==mon.key for row in mons):
            raise JournalError('engine party species/key collision')
        mons.append(mon)
    if kind=='battle_faint':
        slot=integer(point['active_slot'],0,count-1,'active slot')
        # Transform copies the enemy species into wBattleMonSpecies; the owned
        # party slot still identifies the original mon. Do not rekey it here.
        if point['battle_flag'] not in (1,2) or point['battle_hp']!=0:
            raise JournalError('battle engine faint does not identify a zero-HP battler')
        return {'kind':'faint','cause':'battle','key':mons[slot].key,'slot':slot,'blob_hex':mons[slot].raw.hex().upper()}
    if kind=='poison_faint':
        slot=integer(point['which'],0,count-1,'poison slot')
        if point['battle_flag']!=0 or mons[slot].hp!=0 or mons[slot].status!=8:
            raise JournalError('poison engine faint does not identify a poisoned zero-HP mon')
        return {'kind':'faint','cause':'poison','key':mons[slot].key,'slot':slot,'blob_hex':mons[slot].raw.hex().upper()}
    if point['map_id']!=profile['starter_map'] or point['battle_flag']!=0 or point['mon_location']!=0 or point['cur_level']!=5:
        raise JournalError('starter source context differs')
    if kind=='starter_begin':
        if count!=0 or str(point['cur_species']) not in codec.profile['species']:
            raise JournalError('initial starter source needs an empty party and valid species')
        return {'kind':'starter_begin','species_index':point['cur_species']}
    if count!=1 or mons[0].level!=5 or mons[0].species_index!=point['cur_species'] or mons[0].ot_id!=int(point['player_id_hex'],16):
        raise JournalError('starter source did not append the expected first mon')
    return {'kind':'starter_end','key':mons[0].key,'blob_hex':mons[0].raw.hex().upper(),'species_index':mons[0].species_index}


def validate_batch(payload, metadata):
    if not isinstance(payload,dict) or set(payload)!={'schema','source_sha256','variant','context_generation','final_sha1','sequence','signals'}:
        raise JournalError('complete engine signal batch required')
    cartridge=metadata['gen1_metadata']['cartridge']
    if (payload['schema']!=SCHEMA or payload['source_sha256']!=DATA['sha256'] or payload['variant']!=cartridge['variant'] or
            payload['context_generation']!=metadata['control_binding']['context_generation'] or payload['final_sha1']!=cartridge['final_rom_sha1']):
        raise JournalError('engine signal batch differs from admission/source')
    integer(payload['sequence'],1,2**53-1,'sequence')
    if not isinstance(payload['signals'],list) or not 1<=len(payload['signals'])<=32:
        raise JournalError('bounded nonempty engine signal batch required')
    result=[];frame=-1
    for signal in payload['signals']:
        result.append(validate_signal(signal,payload['variant'],metadata['save_identity']))
        if signal['frame']<frame:raise JournalError('engine signal frames moved backwards')
        frame=signal['frame']
    return result
