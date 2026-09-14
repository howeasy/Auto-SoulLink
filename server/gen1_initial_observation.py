"""Initial owned RBY inventory evidence; never invents acquisition or link history."""
import copy
import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict

from server.gen1_full_save import SYMBOLS, image, layout
from server.gen1_native_trade_receipts import _bytes
from server.gen1_party_codec import PartyCodec
from server.identity_registry import IdentityContext
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_identity import SaveIdentity
from server.verified_content_cache import verified_content_cache

SCHEMA='rby-initial-observation-v1'
COMPONENT='gen1-initial-observations'
REASON='Initial inventory observed; gameplay history and execution remain unqualified'


def blocker(run_id,player):return digest({'initial_observation':player,'run_id':run_id})[:32]


def display_name(raw):
    """Match the existing admitted memory_gb display codec; retain raw bytes too.

    Unmapped but codec-valid glyphs display as '?' in the current client. This
    rendering is not a new durable identity or a substitute for raw-name evidence.
    """
    chars={**{0x80+i:chr(65+i) for i in range(26)},**{0xA0+i:chr(97+i) for i in range(26)},
           **{0xF6+i:str(i) for i in range(10)},0x7F:' ',0xE0:"'",0xE1:'P',0xE2:'M',0xE3:'-',
           0xE6:'?',0xE7:'!',0xE8:'.',0xEF:'♂',0xF5:'♀'}
    return ''.join(chars.get(v,'?') for v in raw[:raw.index(0x50)])


def inventory_dependencies():
    """Fresh data inputs to pure decoding; never cache observation authority."""
    from server import gen1_party_codec
    return {
        'codec_sha256': hashlib.sha256(gen1_party_codec.DATA_PATH.read_bytes()).hexdigest(),
        'layouts': {variant: layout(variant) for variant in ('red', 'blue', 'yellow')},
        'identity_offsets': {title: {name: SYMBOLS[title][name] for name in
                                    ('wPlayerID', 'wMainDataStart', 'wCurrentBoxNum')}
                             for title in ('pokered', 'pokeyellow')},
    }


_dependency_scope = ContextVar('gen1-inventory-dependency-scope', default=None)


def scoped_inventory_dependencies():
    proof = _dependency_scope.get()
    return copy.deepcopy(proof) if proof is not None else inventory_dependencies()


@contextmanager
def inventory_dependency_scope():
    """One observation's pure decoder inputs; recheck before any commit.

    The exact source point remains in every validator/cache key.  This scope
    memoizes only the installed codec/layout dependencies while a detached
    state is audited and staged, never the result or an authority decision.
    """
    if _dependency_scope.get() is not None:
        raise JournalError('nested inventory dependency scope')
    proof = inventory_dependencies()
    token = _dependency_scope.set(proof)
    try:
        yield
        if inventory_dependencies() != proof:
            raise JournalError('inventory decoder dependencies changed before commit')
    finally:
        _dependency_scope.reset(token)


@verified_content_cache(dependencies=scoped_inventory_dependencies)
def inventory(source, save):
    """Decode every authoritative slot, excluding the active box's stale SRAM copy."""
    image(source)  # Complete bounded source fields/CartRAM, using pinned save geometry.
    variant=source['variant'];codec=PartyCodec(variant)
    fields=source['fields'];party=_bytes(fields['party'],404);main=_bytes(fields['main'],1929)
    symbols=SYMBOLS['pokeyellow' if variant=='yellow' else 'pokered']
    name=_bytes(fields['name'],11);codec._name(name,'save trainer name')
    decoded=display_name(name)
    player=symbols['wPlayerID']-symbols['wMainDataStart']
    if save!={'ot_id':main[player:player+2].hex().upper(),'trainer_name':decoded}:
        raise JournalError('initial inventory save identity differs from admission')
    current=main[symbols['wCurrentBoxNum']-symbols['wMainDataStart']]
    if current&127>=12:raise JournalError('invalid initial current box')
    cart=_bytes(source['cart_hex'],0x8000)
    members=[];keys=set()
    def add(raw,kind,index,slot):
        mon=codec.validate_blob(raw)
        if mon.key in keys:raise JournalError('initial roster contains a duplicate physical key')
        keys.add(mon.key)
        members.append({'location':kind,'box':index,'slot':slot,'key':mon.key,'blob_hex':raw.hex().upper(),
                        'evidence_digest':hashlib.sha256(raw).hexdigest()})
    count=party[0]
    if count>6 or party[1+count]!=255:raise JournalError('invalid initial party list')
    for slot in range(count):
        raw=party[8+44*slot:8+44*(slot+1)]+party[272+11*slot:272+11*(slot+1)]+party[338+11*slot:338+11*(slot+1)]
        if raw[0]!=party[1+slot]:raise JournalError('initial party species differs')
        add(raw,'party',None,slot)
    boxes=[]
    for index in range(12):
        if index==current&127:raw=_bytes(fields['box'],1122);authoritative=True
        elif current&128:
            offset=(2+index//6)*0x2000+(index%6)*1122;raw=cart[offset:offset+1122];authoritative=True
        else:raw=None;authoritative=False
        boxes.append({'box':index,'authoritative':authoritative,'count':raw[0] if raw else 0})
        if raw is None:continue
        count=raw[0]
        if count>20 or raw[count+1]!=255:raise JournalError('invalid initial box list')
        # Box records are retained as exact bytes. Full party tails are not
        # invented; storage/evolution policy will interpret these witnesses.
        for slot in range(count):
            mon=raw[22+33*slot:22+33*(slot+1)]
            if mon[0]!=raw[slot+1] or str(mon[0]) not in codec.profile['species']:
                raise JournalError('invalid initial boxed species')
            ot=raw[682+11*slot:682+11*(slot+1)];nick=raw[902+11*slot:902+11*(slot+1)]
            codec._ot_name(ot,'boxed OT');codec._name(nick,'boxed nickname')
            key=f'{mon[27:29].hex().upper()}:{mon[12:14].hex().upper()}:{mon[0]:02X}'
            if key in keys:raise JournalError('initial roster contains a duplicate physical key')
            keys.add(key)
            record=mon+ot+nick
            members.append({'location':'box','box':index,'slot':slot,'key':key,'box_blob_hex':record.hex().upper(),
                            'evidence_digest':hashlib.sha256(record).hexdigest()})
    return {'party_count':party[0],'current_box':current&127,'boxes_initialized':bool(current&128),
            'members':members,'boxes':boxes,'source_digest':digest(source)}


def validate(payload, metadata, binding):
    if not isinstance(payload,dict) or set(payload)!={'schema','context_generation','final_sha1','frame','host','source'} or payload['schema']!=SCHEMA:
        raise JournalError('complete initial observation required')
    if (not isinstance(payload['source'],dict) or payload['context_generation']!=binding['context_generation']
            or payload['final_sha1']!=metadata['gen1_metadata']['cartridge']['final_rom_sha1']
            or payload['source'].get('variant')!=metadata['gen1_metadata']['cartridge']['variant']
            or type(payload['frame']) is not int or not 0<=payload['frame']<=2**53-1):
        raise JournalError('initial observation differs from admitted context/cartridge')
    host=payload['host']
    if (not isinstance(host,dict) or set(host)!={'owner_id','capability_id','process_id','held'}
            or host['owner_id']!=metadata['gen1_metadata']['physical_instance']
            or host['capability_id']!='bizhawk-2.11.1-gambatte-exclusive-hold-v1'
            or type(host['process_id']) is not int or host['process_id']<1 or host['held'] is not True):
        raise JournalError('owned held initial observation required')
    return inventory(payload['source'],metadata['save_identity'])


def record(runtime,player,operation,message):
    previous=runtime.journal.event(player,operation,message)
    if previous is not None:return previous.result
    if set(message)!={'event','payload'}:raise JournalError('typed initial observation event required')
    stage=runtime.state();document=stage.document();session=runtime.gate.sessions[player]
    core=document['rules']['core']
    from server.gen1_run_resume import (
        COMPONENT as RESUME,
        enrollment_record,
        inherit_identities,
        save_digest,
        validate_continue_witness,
    )
    resume=document['components'].get(RESUME)
    resuming=resume is not None and (resume['pending'][player] or player in resume['enrolled'])   # a re-attempt fails as immutable
    payload=message['payload'] if isinstance(message['payload'],dict) else {}
    if 'continue_witness' in payload and not resuming:
        raise JournalError('continue witness is only accepted under a pending resume contract')
    established=(document['identities']['members'] or core['links'] or core['area_states']
            or any(core['pending_captures'].values()) or any(core['pokeballs_obtained'].values())
            or any(document['rules']['runtime']['party_keys'].values()))
    if (document['active_trade'] or any(runtime.journal.pending_ids(p) for p in ('a','b')) or established and not resuming):
        raise JournalError('initial enrollment cannot replace established gameplay history or obligations')
    metadata=session.metadata;binding=metadata['control_binding']
    observation={k:v for k,v in payload.items() if k!='continue_witness'}
    result=validate(observation,metadata,binding)
    if resuming:
        # Owner policy P2a: the presented save is the predecessor's witnessed checkpoint, booted via CONTINUE.
        if save_digest(observation['source']['cart_hex'])!=resume['required'][player]['digest']:
            raise JournalError('resume save projection differs from required predecessor witness')
        if 'continue_witness' not in payload:
            raise JournalError('resume enrollment requires a witnessed CONTINUE of the matched save')
        cartridge=metadata['gen1_metadata']['cartridge']
        validate_continue_witness(payload['continue_witness'],variant=cartridge['variant'],context_generation=binding['context_generation'],
            physical_instance=metadata['gen1_metadata']['physical_instance'],final_sha1=cartridge['final_rom_sha1'],frame=observation['frame'])
    entries=document['components'].setdefault(COMPONENT,{})
    if player in entries:raise JournalError('initial observation is immutable; replacement requires reconciliation')
    record={'operation_id':operation,'metadata':copy.deepcopy(metadata),'binding':copy.deepcopy(binding),
            'observation':copy.deepcopy(observation),'inventory':result}
    entries[player]=record
    stage.identities.bind_context(IdentityContext(player,'gen1_rby',SaveIdentity(**metadata['save_identity']),
        digest(metadata['gen1_metadata']['cartridge']),binding['context_generation'],metadata['gen1_metadata']['physical_instance']))
    stage.rules.player_identity[player]=copy.deepcopy(metadata['save_identity'])
    records=[]
    if resuming:
        inherited=inherit_identities(stage,resume,player,record,result,operation)
        resumed=enrollment_record(resume,player,record,copy.deepcopy(payload['continue_witness']),*inherited)
        resume['pending'][player]=False
        resume['enrolled'][player]=resumed
        records.append({'namespace':RESUME,'key':resumed['record_key'],'value':copy.deepcopy(resumed)})
    document['rules']=stage.rules.document();document['identities']=stage.identities.document()
    blockers=stage.barrier.document()['blockers'];blockers[blocker(runtime.journal.run_id,player)]=REASON
    stage.barrier.set_blockers(blockers)
    from server.gen1_runtime_state import recovery_history
    stage.barrier.set_history(recovery_history(document['rules'],document['identities'],document['active_trade'],document['components'].get('gen1-trade')))
    document['components']['gen1-runtime']['recovery']=stage.barrier.document()
    from server.gen1_initial_save_runtime import schedule
    commands, scheduled = schedule(document,player,operation)
    records+=scheduled
    receipt=runtime.journal.commit(player,operation,message,expected_revision=stage.journal_revision,
        state=document,commands=commands,result={'ack':'ACK','inventory_digest':digest(result),'ordinary_execution':False},records=records)
    return receipt.result


def verify_state(stage):
    document=stage.document();entries=document['components'].get(COMPONENT,{})
    if not isinstance(entries,dict) or set(entries)-{'a','b'}:raise JournalError('invalid initial inventory records')
    expected={}
    for player,entry in entries.items():
        if not isinstance(entry,dict) or set(entry)!={'operation_id','metadata','binding','observation','inventory'}:
            raise JournalError('incomplete initial inventory record')
        if not isinstance(entry['operation_id'],str) or not re.fullmatch('[0-9a-f]{32}',entry['operation_id']):
            raise JournalError('invalid initial observation operation')
        from server.gen1_runtime_admission import validate_hello
        metadata=entry['metadata'];binding=entry['binding']
        if not isinstance(metadata,dict) or not isinstance(binding,dict) or set(binding)!={'session_id','admission_epoch','context_generation','binding_digest'}:
            raise JournalError('initial observation lacks its admission binding')
        checked=validate_hello(stage.component['contract'],player,{'gen1_metadata':metadata.get('gen1_metadata'),
            'run_id':stage.identities.document()['run_id']},run_id=stage.identities.document()['run_id'],contract_validator=stage.validate_contract)
        if {k:v for k,v in metadata.items() if k!='control_binding'}!=checked or metadata.get('control_binding')!=binding:
            raise JournalError('initial metadata differs from the admitted contract')
        expected_binding=digest({'player':player,'metadata':checked,**{k:binding[k] for k in ('session_id','admission_epoch','context_generation')}})
        if binding['binding_digest']!=expected_binding:raise JournalError('initial admission binding digest differs')
        if validate(entry['observation'],entry['metadata'],entry['binding'])!=entry['inventory']:
            raise JournalError('initial inventory record differs from its evidence')
        if entry['metadata']['player']!=player:raise JournalError('initial inventory belongs to another player')
        context=IdentityContext(player,'gen1_rby',SaveIdentity(**metadata['save_identity']),digest(metadata['gen1_metadata']['cartridge']),
                                binding['context_generation'],metadata['gen1_metadata']['physical_instance'])
        if not any(row['context']==asdict(context) for row in document['identities']['context_history'][player]):
            raise JournalError('initial inventory context is absent from identity history')
        expected[blocker(stage.identities.document()['run_id'],player)]=REASON
    actual={key:value for key,value in stage.barrier.document()['blockers'].items() if value==REASON}
    if actual!=expected:raise JournalError('initial inventory hold differs from recorded evidence')
