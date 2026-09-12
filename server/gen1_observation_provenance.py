"""Bind RBY semantic evidence to standalone or compound frame events."""

import copy
import re

from server import event_reference
from server.gen1_frame_runtime import COMPONENT, bundle_boundary, validate_state
from server.protocol import digest
from server.protocol_journal import EventReceipt, JournalError


def validate_entry_origin(entry, player=None):
    if 'frame_origin' not in entry:
        return None
    origin = event_reference.validate(entry['frame_origin'])
    if origin['operation_id'] != entry['operation_id'] or player is not None and origin['player'] != player:
        raise JournalError('frame observation belongs to another operation or player')
    return origin


def _bundle(request):
    if isinstance(request, dict) and request.get('event') == 'native_frame_handoff':
        if set(request) != {'event', 'payload'} or not isinstance(request['payload'], dict):
            raise JournalError('complete native handoff observation required')
        payload = request['payload']
        inventory, checkpoint = payload.get('inventory'), payload.get('native_checkpoint')
        if (payload.get('schema') != 'rby-native-frame-return-v1' or not isinstance(inventory, dict)
                or not isinstance(checkpoint, dict) or not isinstance(payload.get('host'), dict)
                or payload['host'].get('frame') != inventory.get('frame')):
            raise JournalError('native handoff lacks its held source checkpoint')
        bundle = {'inventory': inventory, 'engine_signals': None,
                  'native_checkpoint': {'schema': 'rby-native-observation-v1', 'party': checkpoint.get('party')}}
        bundle_boundary(bundle)
        return bundle
    if not isinstance(request, dict) or set(request) != {'event', 'receipt', 'bundle'} or request['event'] != 'frame_complete':
        raise JournalError('complete compound frame event required')
    bundle, receipt = request['bundle'], request['receipt']
    boundary = bundle_boundary(bundle)
    if (not isinstance(receipt, dict)
            or receipt.get('observations_digest') != digest(bundle)
            or receipt.get('after') != boundary['frame']):
        raise JournalError('compound frame event differs from its held bundle')
    return bundle


observation_bundle = _bundle


def _contained(request, semantic):
    bundle = _bundle(request)
    if semantic['event'] == 'engine_signals':
        matches = bundle['engine_signals'] is not None and semantic['payload'] == bundle['engine_signals']
    elif semantic['event'] == 'inventory_observation':
        matches = bundle['inventory'] is not None and semantic['payload']['observation'] == bundle['inventory']
    elif semantic['event'] == 'acquisition_observation':
        matches = semantic['payload']['receipts'] == (bundle.get('acquisitions') or [])
    else:
        raise JournalError('unknown frame observation semantic kind')
    if not matches:
        raise JournalError('semantic observation differs from its compound frame bundle')


def stage_origin(document, player, operation, semantic_request, *, frame_origin=None, frame_request=None):
    framed = player in document['components'].get(COMPONENT, {})
    if frame_origin is None and frame_request is None:
        if framed:
            raise JournalError('frame-accounted observations require their compound frame origin')
        return None
    if frame_origin is None or frame_request is None or not framed:
        raise JournalError('compound observations require an owned frame origin and request')
    origin = event_reference.validate(frame_origin)
    if origin != event_reference.make(player, operation, frame_request):
        raise JournalError('compound frame origin differs from the staged operation')
    _contained(frame_request, semantic_request)
    validate_state(document)
    entry = document['components'][COMPONENT][player]
    pending = entry['pending_observation']
    if frame_request.get('event') == 'native_frame_handoff':
        native = document['components'].get('gen1-native-frame-accounting', {}).get(player)
        expected = digest({'event': 'native_frame_return', 'payload': frame_request['payload']})
        if (pending is None or native is None or native['phase'] != 'handed_back'
                or native['head']['operation_id'] != operation or native['closed'] != pending['closed']
                or pending['bundle_digest'] != expected
                or pending['closed']['receipt']['after'] != frame_request['payload']['inventory']['frame']):
            raise JournalError('native observations lack their verified final handoff')
    elif (pending is None or pending['closed']['receipt'] != frame_request['receipt']
          or pending['bundle_digest'] != digest(frame_request['bundle'])):
        raise JournalError('compound observation lacks its closed pending frame range')
    if document['active_trade']:
        raise JournalError('native trade owns observation settlement until verified closure')
    return copy.deepcopy(origin)


def semantic_receipt(journal, player, entry, kind):
    """Return a legacy-shaped receipt after checking the containing frame event."""
    if kind == 'engine_signals':
        semantic = {'event': kind, 'payload': entry['payload']}
        field = 'engine_evidence_digest'
    elif kind == 'inventory_observation':
        semantic = {'event': kind, 'payload': {
            'sequence': entry['sequence'], 'previous_operation_id': entry['previous_operation_id'],
            'observation': entry['observation']}}
        field = 'inventory_transition_digest'
    else:
        raise JournalError('unknown observation receipt kind')
    origin = validate_entry_origin(entry, player)
    if origin is None:
        outer = journal.event_snapshot(player, entry['operation_id'])
        if outer is None or outer.request.get('event') != 'observation':
            return journal.event(player, entry['operation_id'], semantic)
        # A free-run observation (P10) contains its semantics the way a compound frame does.
        contained = outer.request.get('signals') if kind == 'engine_signals' else outer.request.get('inventory')
        expected = semantic['payload'] if kind == 'engine_signals' else semantic['payload']['observation']
        if contained is None or contained != expected or outer.result.get(field) != digest(entry):
            raise JournalError('free-run observation differs from its semantic evidence digest')
        return EventReceipt(outer.revision, {'ack': 'ACK', field: digest(entry), 'ordinary_execution': False}, outer.command_ids)
    outer = event_reference.resolve(journal, origin)
    _contained(outer.request, semantic)
    result = outer.result
    bundle = _bundle(outer.request)
    required = {'ack', 'ordinary_execution', 'closed_frame_digest', 'observations_settled'}
    if outer.request['event'] == 'native_frame_handoff':
        required.update({'native_handoff', 'native_frame_digest'})
        if result.get('native_handoff') is not True:
            raise JournalError('native observation lacks its completed handoff')
    if bundle['inventory'] is not None:
        required.add('inventory_transition_digest')
    if bundle['engine_signals'] is not None:
        required.add('engine_evidence_digest')
    if 'acquisition_digest' in result or bundle.get('acquisitions'):
        required.update({'acquisition_digest','static_digest','exchange_digest'})
    if ('wild_encounter_digest' in result or any(row['kind'] in ('wild_begin','wild_end','capture')
            for row in bundle.get('acquisitions') or [])):
        required.add('wild_encounter_digest')
    if any(row['kind'] == 'evolution' for row in bundle.get('acquisitions') or []):
        required.add('evolution_digest')
    if bundle.get('native_checkpoint') is not None:
        required.add('native_checkpoint_digest')
    if (set(result) != required or result['ack'] != 'ACK' or result['ordinary_execution'] is not False
            or result['observations_settled'] is not True):
        raise JournalError('compound frame event has not settled its observations')
    for name in required - {'ack', 'ordinary_execution', 'observations_settled', 'native_handoff'}:
        if not isinstance(result[name], str) or not re.fullmatch('[0-9a-f]{64}', result[name]):
            raise JournalError('compound frame result lacks its complete evidence digest')
    if result[field] != digest(entry):
        raise JournalError('compound frame event differs from its semantic evidence digest')
    return EventReceipt(outer.revision, {'ack': 'ACK', field: digest(entry), 'ordinary_execution': False}, outer.command_ids)
