"""Bind RBY semantic evidence to its containing event.

Two containers remain now that the frame-credit loop is retired: a free-run ``observation``
batch (P10, gen1_observation_runtime), which carries its engine signals, inventory and the one
source-receipt list (``acquisitions``: captures, grants, static origins/ends, NPC exchanges,
wild boundaries, evolutions) inline, and a ``native_frame_handoff``, the compound event a
handed-back native loan settles its final inventory and native checkpoint through
(gen1_native_frame_accounting). The settlement modules key their verifiers on the committing
event: ``batch_origin`` is that rule for a free-run batch, ``contained_receipts`` and
``contained_inventory`` name what a committed event carries.
"""

import copy
import re

from server import event_reference
from server.gen1_native_frame_accounting import FRAMES, validate_ledger
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
    if not isinstance(request, dict) or request.get('event') != 'native_frame_handoff':
        raise JournalError('native frame handoff event required')
    if set(request) != {'event', 'payload'} or not isinstance(request['payload'], dict):
        raise JournalError('complete native handoff observation required')
    payload = request['payload']
    inventory, checkpoint = payload.get('inventory'), payload.get('native_checkpoint')
    if (payload.get('schema') != 'rby-native-frame-return-v1' or not isinstance(inventory, dict)
            or not isinstance(checkpoint, dict) or not isinstance(payload.get('host'), dict)
            or payload['host'].get('frame') != inventory.get('frame')):
        raise JournalError('native handoff lacks its held source checkpoint')
    return {'inventory': inventory, 'engine_signals': None,
            'native_checkpoint': {'schema': 'rby-native-observation-v1', 'party': checkpoint.get('party')}}


observation_bundle = _bundle


def contained_receipts(request):
    """The raw ``{kind, receipt}`` list an event carries (a free-run batch's ``acquisitions``, a compound
    frame's ``bundle.acquisitions``), or None when the event carries no source receipts."""
    kind = request.get('event') if isinstance(request, dict) else None
    if kind == 'observation':
        return request.get('acquisitions') or []
    if kind == 'frame_complete':
        return request.get('bundle', {}).get('acquisitions') or []
    return None


def contained_inventory(request):
    """The inventory checkpoint an event carries (a free-run batch, a compound frame, a standalone
    ``inventory_observation``), or None."""
    kind = request.get('event') if isinstance(request, dict) else None
    if kind == 'observation':
        return request.get('inventory')
    if kind == 'frame_complete':
        return request.get('bundle', {}).get('inventory')
    if kind == 'inventory_observation':
        return request.get('payload', {}).get('observation')
    return None


def batch_origin(event, entry, field):
    """True when ``event`` (the snapshot of the event that committed ``entry``) is a free-run observation
    batch: P10 verifiers key on the committing event, whose result must carry ``digest(entry)`` under
    ``field`` (acquisition_digest, exchange_digest, evolution_digest). False for any other event."""
    if event is None or event.request.get('event') != 'observation':
        return False
    if event.result.get(field) != digest(entry):
        raise JournalError('free-run observation differs from its semantic evidence digest')
    return True


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
    framed = player in document['components'].get(FRAMES, {})
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
    validate_ledger(document)
    pending = document['components'][FRAMES][player]['pending_observation']
    native = document['components'].get('gen1-native-frame-accounting', {}).get(player)
    expected = digest({'event': 'native_frame_return', 'payload': frame_request['payload']})
    if (pending is None or native is None or native['phase'] != 'handed_back'
            or native['head']['operation_id'] != operation or native['closed'] != pending['closed']
            or pending['bundle_digest'] != expected
            or pending['closed']['receipt']['after'] != frame_request['payload']['inventory']['frame']):
        raise JournalError('native observations lack their verified final handoff')
    if document['active_trade']:
        raise JournalError('native trade owns observation settlement until verified closure')
    return copy.deepcopy(origin)


def semantic_receipt(journal, player, entry, kind):
    """Return a legacy-shaped receipt after checking the containing event."""
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
    required = {'ack', 'ordinary_execution', 'closed_frame_digest', 'observations_settled',
                'native_handoff', 'native_frame_digest', 'inventory_transition_digest', 'native_checkpoint_digest'}
    if result.get('native_handoff') is not True:
        raise JournalError('native observation lacks its completed handoff')
    if (set(result) != required or result['ack'] != 'ACK' or result['ordinary_execution'] is not False
            or result['observations_settled'] is not True):
        raise JournalError('compound frame event has not settled its observations')
    for name in required - {'ack', 'ordinary_execution', 'observations_settled', 'native_handoff'}:
        if not isinstance(result[name], str) or not re.fullmatch('[0-9a-f]{64}', result[name]):
            raise JournalError('compound frame result lacks its complete evidence digest')
    if result[field] != digest(entry):
        raise JournalError('compound frame event differs from its semantic evidence digest')
    return EventReceipt(outer.revision, {'ack': 'ACK', field: digest(entry), 'ordinary_execution': False}, outer.command_ids)
