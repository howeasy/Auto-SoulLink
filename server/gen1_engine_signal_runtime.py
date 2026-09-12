"""Atomic engine evidence and paired starter-call interpretation under admission."""
import copy

from server.admission_context import same_admitted_context
from server.gen1_engine_signals import validate_batch
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_observation_provenance import semantic_receipt, stage_origin, validate_entry_origin
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT='gen1-engine-signals'


def key(player):return digest({'component':COMPONENT,'player':player})[:32]


def interpret(payload, metadata, pending=None):
    decoded=validate_batch(payload,metadata);pending=copy.deepcopy(pending);transactions=[]
    for signal,result in zip(payload['signals'],decoded,strict=True):
        if result['kind']=='starter_begin':
            if pending is not None:raise JournalError('overlapping starter source calls require recovery')
            pending=copy.deepcopy(signal)
        elif result['kind']=='starter_end':
            if pending is None:raise JournalError('starter return has no observed call')
            if (signal['frame']<pending['frame'] or signal['sp']!=pending['sp'] or
                    signal['point']['cur_species']!=pending['point']['cur_species'] or
                    signal['point']['map_id']!=pending['point']['map_id']):
                raise JournalError('starter call and return context differ')
            transactions.append({'kind':'scripted_grant','source_id':'grant:starter:0',
                'key':result['key'],'blob_hex':result['blob_hex'],'before':pending,'after':copy.deepcopy(signal)})
            pending=None
        else:
            transactions.append({**result,'frame':signal['frame']})
    return pending,transactions


def verify_state(stage):
    document=stage.document();entries=document['components'].get(COMPONENT,{})
    if not isinstance(entries,dict) or set(entries)-{'a','b'}:raise JournalError('invalid engine signal component')
    for player,entry in entries.items():
        if not isinstance(entry,dict) or set(entry)-{'frame_origin'}!={'operation_id','payload','prior_starter','pending_starter','transactions'}:
            raise JournalError('incomplete engine signal record')
        validate_entry_origin(entry,player)
        initial=document['components'].get(INITIAL,{}).get(player)
        if initial is None:raise JournalError('engine signals require initial context')
        from server.protocol_journal import _identifier
        _identifier(entry['operation_id'])
        prior=entry['prior_starter']
        if prior is not None:
            from server.gen1_engine_signals import validate_signal
            if validate_signal(prior,entry['payload']['variant'],initial['metadata']['save_identity'])['kind']!='starter_begin':
                raise JournalError('pending starter record is not a source call')
        pending,transactions=interpret(entry['payload'],initial['metadata'],prior)
        if pending!=entry['pending_starter'] or transactions!=entry['transactions']:
            raise JournalError('engine signal record differs from source evidence')
        if entry['payload']['signals'][0]['frame']<initial['observation']['frame']:
            raise JournalError('engine signal predates initial inventory')


def record(runtime,player,operation,request):
    stage=runtime.state()
    previous=runtime.journal.event(player,operation,request)
    if previous is not None:return previous.result
    document=stage.document()
    staged=stage_observation(runtime,stage,document,player,operation,request)
    return runtime.journal.commit(player,operation,request,expected_revision=stage.journal_revision,state=document,
        commands=staged['commands'],result=staged['result'],records=staged['records']).result


def stage_observation(runtime,stage,document,player,operation,request,*,frame_origin=None,frame_request=None,
                      allow_transport_rotation=False):
    """Stage evidence on caller-owned state; return entry/result/commands/records.

    Only the detached stage/document may change. Journal/session reads retain
    existing admission and obligation checks; no event or command is published.
    Discard both detached values if validation fails.
    """
    if set(request)!={'event','payload'}:raise JournalError('typed engine signal event required')
    origin=stage_origin(document,player,operation,request,frame_origin=frame_origin,frame_request=frame_request)
    initial=document['components'].get(INITIAL,{}).get(player)
    if initial is None:raise JournalError('engine signals require initial enrollment')
    metadata=runtime.gate.sessions[player].metadata
    matching=same_admitted_context(metadata,initial['metadata']) if origin or allow_transport_rotation else metadata==initial['metadata']
    if not matching:raise JournalError('engine signal source context changed; recovery required')
    entries=document['components'].setdefault(COMPONENT,{})
    old=entries.get(player);payload=request['payload']
    validate_batch(payload,metadata)
    if payload['sequence']!=(old['payload']['sequence']+1 if old else 1):
        raise JournalError('engine signal sequence skipped or repeated')
    prior_frame=old['payload']['signals'][-1]['frame'] if old else initial['observation']['frame']
    if payload['signals'][0]['frame']<prior_frame:raise JournalError('engine signal frame moved backwards')
    pending=old['pending_starter'] if old else None
    remaining,transactions=interpret(payload,metadata,pending)
    entry={'operation_id':operation,'payload':copy.deepcopy(payload),'prior_starter':copy.deepcopy(pending),
           'pending_starter':remaining,'transactions':transactions}
    if origin is not None:entry['frame_origin']=origin
    entries[player]=entry
    from server.gen1_starter_settlement import remember_source
    remember_source(document,player,entry)
    from server.gen1_faint_runtime import settle
    commands=settle(runtime,stage,document,player,entry)
    return {'entry':entry,'commands':commands,
        'result':{'ack':'ACK','engine_evidence_digest':digest(entry),'ordinary_execution':False},
        'records':[{'namespace':COMPONENT,'key':key(player),'value':entry}]}


def verify_journal(journal,stage):
    entries=stage.document()['components'].get(COMPONENT,{})
    for player in ('a','b'):
        record=journal.record(COMPONENT,key(player));entry=entries.get(player)
        if (record is None)!=(entry is None) or record is not None and record.value!=entry:
            raise JournalError('engine evidence differs from its atomic audit record')
        if entry is not None:
            receipt=semantic_receipt(journal,player,entry,'engine_signals')
            expected={'ack':'ACK','engine_evidence_digest':digest(entry),'ordinary_execution':False}
            if receipt is None or receipt.result!=expected or receipt.revision!=record.revision:
                raise JournalError('engine evidence lacks its committed event')
