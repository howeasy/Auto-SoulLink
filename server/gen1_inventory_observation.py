"""Ordered held inventory evidence. Rule/history qualification remains mandatory."""
import copy
import re

from server.admission_context import same_admitted_context
from server.gen1_initial_observation import COMPONENT as INITIAL, validate
from server.gen1_inventory_transition import transition
from server.gen1_observation_provenance import semantic_receipt, stage_origin, validate_entry_origin
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = 'gen1-inventory-observations'


def record_key(player):
    return digest({'component': COMPONENT, 'player': player})[:32]


def message(entry):
    return {'event': 'inventory_observation', 'payload': {
        'sequence': entry['sequence'], 'previous_operation_id': entry['previous_operation_id'],
        'observation': entry['observation']}}


def result(entry):
    return {'ack': 'ACK', 'inventory_transition_digest': digest(entry), 'ordinary_execution': False}


def verify_entry(entry, initial):
    if not isinstance(entry, dict) or set(entry)-{'frame_origin', 'write_attribution'} != {
            'sequence', 'operation_id', 'previous_operation_id', 'before', 'observation', 'transition'}:
        raise JournalError('complete inventory transition required')
    validate_entry_origin(entry)
    if type(entry['sequence']) is not int or not 1 <= entry['sequence'] <= 2**53-1:
        raise JournalError('invalid inventory observation sequence')
    for field in ('operation_id', 'previous_operation_id'):
        if not isinstance(entry[field], str) or not re.fullmatch('[0-9a-f]{32}', entry[field]):
            raise JournalError('invalid inventory observation cursor')
    if entry['operation_id'] == entry['previous_operation_id']:
        raise JournalError('inventory observation cannot precede itself')
    before, after = entry['before'], entry['observation']
    for point in (before, after):
        validate(point, initial['metadata'], initial['binding'])
        if point['host'] != initial['observation']['host']:
            raise JournalError('inventory observation host changed; reconciliation required')
    if after['frame'] <= before['frame'] or before['frame'] < initial['observation']['frame']:
        raise JournalError('inventory observation must advance its frame')
    if entry['sequence'] == 1 and (entry['previous_operation_id'] != initial['operation_id']
                                    or before != initial['observation']):
        raise JournalError('inventory stream is not rooted in initial enrollment')
    expected = transition(before['source'], after['source'], initial['metadata']['save_identity'],
                          attribution=entry.get('write_attribution'))
    if entry['transition'] != expected:
        raise JournalError('inventory transition differs from its physical evidence')


def verify_state(stage):
    document = stage.document()
    entries = document['components'].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries)-{'a', 'b'}:
        raise JournalError('invalid inventory observation component')
    for player, entry in entries.items():
        initial = document['components'].get(INITIAL, {}).get(player)
        if initial is None:
            raise JournalError('inventory observation requires initial enrollment')
        verify_entry(entry, initial)


def verify_journal(journal, stage):
    entries = stage.document()['components'].get(COMPONENT, {})
    for player in ('a', 'b'):
        stored = journal.record(COMPONENT, record_key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError('inventory component differs from its atomic journal record')
        if entry is not None:
            receipt = semantic_receipt(journal, player, entry, 'inventory_observation')
            if receipt is None or receipt.result != result(entry) or receipt.revision != stored.revision:
                raise JournalError('inventory observation lacks its exact committed event')
            if 'write_attribution' in entry:
                from server.gen1_authorized_inventory import build, predecessor_receipt
                plan = entry['write_attribution']
                initial = stage.document()['components'][INITIAL][player]
                if entry['sequence'] == 1:
                    prior = predecessor_receipt(journal, player, initial, None)
                else:
                    history = journal.record_history(COMPONENT, record_key(player),
                        after_revision=plan['after_revision']-1, limit=1)
                    if not history or history[0].revision != plan['after_revision']:
                        raise JournalError('attributed inventory predecessor record is missing')
                    old = history[0].value
                    if (old['operation_id'] != entry['previous_operation_id'] or old['observation'] != entry['before']
                            or old['sequence']+1 != entry['sequence']):
                        raise JournalError('attributed inventory predecessor differs')
                    prior = predecessor_receipt(journal, player, initial, old)
                if prior is None or prior.revision != plan['after_revision'] or plan['through_revision'] != stored.revision-1:
                    raise JournalError('inventory mutation interval differs from committed observation order')
                expected = build(journal, stage.document(), player, entry['before'], entry['observation'],
                    after_revision=prior.revision, through_revision=stored.revision-1, historical=True)
                if plan != expected:
                    raise JournalError('inventory attribution differs from its verified command ACKs')
            else:
                # Legacy raw-only entries are compatible only when no proved
                # command effect was omitted from their observed interval.
                from server.gen1_authorized_inventory import build
                prior = journal.event_snapshot(player, entry['previous_operation_id'])
                if prior is None:
                    raise JournalError('legacy inventory predecessor event is missing')
                expected = build(journal, stage.document(), player, entry['before'], entry['observation'],
                    after_revision=prior.revision, through_revision=stored.revision-1, historical=True)
                if expected['writes']:
                    raise JournalError('inventory transition omitted its authorized write attribution')


def record(runtime, player, operation, request):
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    _typed_request(request)
    stage = runtime.state()
    document = stage.document()
    staged = stage_observation(runtime, stage, document, player, operation, request)
    return runtime.journal.commit(player, operation, request, expected_revision=stage.journal_revision,
        state=document, commands=staged['commands'], result=staged['result'], records=staged['records']).result


def _typed_request(request):
    if set(request) != {'event', 'payload'} or not isinstance(request['payload'], dict) or set(request['payload']) != {
            'sequence', 'previous_operation_id', 'observation'}:
        raise JournalError('typed inventory observation required')


def stage_observation(runtime, stage, document, player, operation, request, *, frame_origin=None, frame_request=None):
    """Stage evidence on caller-owned state; return entry/result/commands/records.

    Only the detached stage/document may change. Journal/session reads retain
    existing admission and obligation checks; no event or command is published.
    Discard both detached values if validation fails.
    """
    _typed_request(request)
    origin = stage_origin(document, player, operation, request, frame_origin=frame_origin, frame_request=frame_request)
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('inventory observation requires initial enrollment')
    metadata = runtime.gate.sessions[player].metadata
    matching = same_admitted_context(metadata, initial['metadata']) if origin else metadata == initial['metadata']
    if not matching:
        raise JournalError('inventory stream context changed; reconciliation required')
    from server.gen1_hud_feedback import pending_physical_ids

    if document['active_trade'] or origin is None and pending_physical_ids(runtime.journal, player):
        raise JournalError('physical command obligations require their own observation closure')
    entries = document['components'].setdefault(COMPONENT, {})
    old = entries.get(player)
    sequence = old['sequence']+1 if old else 1
    predecessor = old['operation_id'] if old else initial['operation_id']
    payload = request['payload']
    if type(payload['sequence']) is not int or payload['sequence'] != sequence or payload['previous_operation_id'] != predecessor:
        raise JournalError('inventory observation skipped or replaced its predecessor')
    before = old['observation'] if old else initial['observation']
    after = payload['observation']
    validate(after, metadata, initial['binding'])
    from server.gen1_authorized_inventory import build, predecessor_receipt
    previous_receipt = predecessor_receipt(runtime.journal, player, initial, old)
    attribution = build(runtime.journal, document, player, before, after,
                        after_revision=previous_receipt.revision, through_revision=stage.journal_revision)
    entry = {'sequence': sequence, 'operation_id': operation, 'previous_operation_id': predecessor,
             'before': copy.deepcopy(before), 'observation': copy.deepcopy(after),
             'write_attribution': attribution,
             'transition': transition(before['source'], after['source'], metadata['save_identity'], attribution=attribution)}
    if origin is not None:
        entry['frame_origin'] = origin
    verify_entry(entry, initial)
    entries[player] = entry
    from server.gen1_starter_settlement import settle_ready
    feedback = settle_ready(runtime, stage, document, frame_origin=origin)
    from server.gen1_rule_inventory import refresh_party
    refresh_party(stage.rules, player, after, initial['metadata']['save_identity'])
    document['rules'] = stage.rules.document()
    # The history/execution blocker stays until the ordinary lifecycle qualifies.
    # Only a separately proved starter source can settle from this checkpoint.
    return {'entry': entry, 'commands': feedback, 'result': result(entry),
        'records': [{'namespace': COMPONENT, 'key': record_key(player), 'value': entry}]}
