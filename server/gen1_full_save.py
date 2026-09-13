"""Original SaveGameData field copies/checksum, applied from one held snapshot.

The layout comes from the pinned pret symbols. SRAM outside sGameData and its
checksum is preserved, including Hall of Fame and all inactive box storage.
"""
import json
from pathlib import Path

from server.gen1_native_trade_receipts import _bytes
from server.gen1_trade_preparation import validate_checkpoint
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image

ROOT=Path(__file__).resolve().parents[1]
SYMBOLS=json.loads((ROOT/'data/pret_syms.json').read_text())
POINT='rby-full-save-point-v1'


def layout(variant):
    if variant not in {'red','blue','yellow'}:raise JournalError('RBY full-save variant required')
    symbols=SYMBOLS['pokeyellow' if variant=='yellow' else 'pokered']
    pairs=[('name','wPlayerName',None,'sPlayerName'),('main','wMainDataStart','wMainDataEnd','sMainData'),
           ('sprites','wSpriteDataStart','wSpriteDataEnd','sSpriteData'),('box','wBoxDataStart','wBoxDataEnd','sCurBoxData'),
           ('party','wPartyDataStart','wPartyDataEnd','sPartyData'),('tiles','hTileAnimations',None,'sTileAnimations')]
    regions={name:{'address':symbols[start],'length':symbols[end]-symbols[start] if end else 11 if name=='name' else 1,
                   'target':symbols[target]-0x8000} for name,start,end,target in pairs}
    result={'regions':regions,'status':symbols['wSaveFileStatus'],
            'start':symbols['sGameData']-0x8000,'end':symbols['sGameDataEnd']-0x8000,
            'checksum':symbols['sMainDataCheckSum']-0x8000}
    assert result['end']==result['checksum'] and 0x2000<=result['start']<result['end']<0x4000
    cursor=result['start']
    for begin,end in sorted((r['target'],r['target']+r['length']) for r in regions.values()):
        assert begin==cursor
        cursor=end
    assert cursor==result['end']
    return result


def image(point):
    if not isinstance(point,dict) or set(point)!={'schema','variant','cart_hex','fields','save_status'} or point['schema']!=POINT:
        raise JournalError('complete full-save point required')
    info=layout(point['variant'])
    if not isinstance(point['fields'],dict) or set(point['fields'])!=set(info['regions']):
        raise JournalError('complete source-defined full-save fields required')
    if type(point['save_status']) is not int or not 0<=point['save_status']<=255:
        raise JournalError('full-save status byte required')
    result=bytearray(_bytes(point['cart_hex'],0x8000))
    for name,region in info['regions'].items():
        raw=_bytes(point['fields'][name],region['length'])
        result[region['target']:region['target']+region['length']]=raw
    result[info['checksum']]=(255-sum(result[info['start']:info['end']]))&255
    return bytes(result)


def matches_checkpoint(point, checkpoint):
    """Tie the wider save snapshot to already validated party/current-box evidence."""
    if (point['variant']!=checkpoint['party']['variant'] or point['cart_hex']!=checkpoint['cart_hex']
            or point['fields']['name']!=checkpoint['name_hex']
            or point['fields']['party']!=checkpoint['party_storage_hex']
            or point['fields']['box']!=checkpoint['active_box_hex']):
        raise JournalError('full-save source differs from the owned trade checkpoint')
    symbols=SYMBOLS['pokeyellow' if point['variant']=='yellow' else 'pokered']
    main=_bytes(point['fields']['main'],layout(point['variant'])['regions']['main']['length'])
    player=symbols['wPlayerID']-symbols['wMainDataStart']
    if main[player:player+2].hex().upper()!=checkpoint['party']['save_id']:
        raise JournalError('full-save player identity differs from the owned checkpoint')
    for name,value in (('wCurMap',checkpoint['map']),('wCurrentBoxNum',checkpoint['current_box'])):
        if main[symbols[name]-symbols['wMainDataStart']]!=value:
            raise JournalError('full-save map/box differs from the owned checkpoint')
    return True


def window(policy, player, command, native, binding, trade, previous):
    if trade['phase'] not in {'preparing','both_prepared'}:return None
    if set(native)!={'phase','intent','current','before','after'} or native['phase']!='full_save':
        raise JournalError('complete full-save window evidence required')
    intent=native['intent'];body=command['body']
    fields={'schema','command_id','command_sequence','body_digest','context_generation','point','checkpoint','image_hex'}
    if (not isinstance(intent,dict) or set(intent)!=fields or intent['schema']!='rby-full-save-intent-v1'
            or intent['command_id']!=command['command_id'] or type(intent['command_sequence']) is not int
            or intent['command_sequence']!=command['command_sequence'] or intent['body_digest']!=digest(body)
            or intent['context_generation']!=binding['context_generation']):
        raise JournalError('full-save intent differs from its command/context')
    validate_checkpoint(intent['checkpoint'],rules=policy.rules[player],participant=trade['proposal']['participants'][player])
    expected=image(intent['point']);matches_checkpoint(intent['point'],intent['checkpoint'])
    if intent['image_hex']!=expected.hex().upper():raise JournalError('full-save image differs from cartridge copies')
    current=native['current'];image(current)
    if current['variant']!=intent['point']['variant'] or current['fields']!=intent['point']['fields']:
        raise JournalError('full-save WRAM changed after preparation')
    before=current==intent['point']
    after=current['cart_hex']==intent['image_hex'] and current['save_status']==2
    if (type(native['before']) is not bool or type(native['after']) is not bool
            or native['before']!=before or native['after']!=after or not (before or after)):
        raise JournalError('partial or foreign full-save state')
    previous_save=previous if previous and previous.get('full_save_point') is not None else None
    fingerprint=digest(intent)
    if previous_save and fingerprint!=previous_save['intent_digest']:
        raise JournalError('full-save intent changed within its binding')
    if after and not before and previous_save is None:
        raise JournalError('full-save mutation lacks its initial verified window')
    if previous_save and previous_save['armed'] and not after:
        raise JournalError('completed full-save image regressed')
    return fingerprint,after,{'full_save_point':intent['point'],'save_image_hex':intent['image_hex']}


def verify_receipt(policy, trade, player, command, receipt, checkpoint):
    fields={'schema','command_id','command_sequence','context_generation','final_sha1','point','image_hex','file'}
    if not isinstance(receipt,dict) or set(receipt)!=fields or receipt['schema']!='rby-full-save-receipt-v1':
        raise JournalError('complete full-save file receipt required')
    own=trade['proposal']['participants'][player]
    if (receipt['command_id']!=command['command_id'] or type(receipt['command_sequence']) is not int
            or receipt['command_sequence']!=command['command_sequence']
            or receipt['context_generation']!=own['context']['context_generation']
            or receipt['final_sha1']!=policy.manifests[player]['final_sha1']):
        raise JournalError('full-save receipt belongs to another command/context')
    binding=policy.runtime.gate.sessions[player].metadata['control_binding']
    from server.gen1_native_progress import progress_for
    previous=progress_for(policy.execution,player,command['command_id'],binding)
    if (previous is None or receipt['point']!=previous.get('full_save_point')
            or receipt['image_hex']!=previous.get('save_image_hex')):
        raise JournalError('full save lacks its owned initial window')
    expected=image(receipt['point'])
    if receipt['image_hex']!=expected.hex().upper() or checkpoint['cart_hex']!=receipt['image_hex']:
        raise JournalError('preparation differs from the verified full save')
    after_point={**receipt['point'],'cart_hex':receipt['image_hex'],'save_status':2}
    matches_checkpoint(after_point,checkpoint)
    verify_file_image(receipt['file'],expected,host_profile='bizhawk-2.11.1-gambatte-exclusive-hold-v1',
                      frame_from=previous['frame'],frame_to=previous['frame'])
    return receipt
