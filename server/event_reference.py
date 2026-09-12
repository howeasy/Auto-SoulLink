"""Checked references to existing atomic events; no execution authority."""

import re

from server.protocol_journal import JournalError, _encode, _identifier, _player

SCHEMA = 'slink-event-reference-v1'


def validate(reference):
    if not isinstance(reference, dict) or set(reference) != {
            'schema', 'player', 'operation_id', 'request_digest'} or reference['schema'] != SCHEMA:
        raise JournalError('complete event reference required')
    _player(reference['player'])
    _identifier(reference['operation_id'])
    if not isinstance(reference['request_digest'], str) or not re.fullmatch('[0-9a-f]{64}', reference['request_digest']):
        raise JournalError('complete event request digest required')
    return dict(reference)


def make(player, operation_id, request):
    _player(player)
    _identifier(operation_id)
    _, fingerprint = _encode(request)
    return {'schema': SCHEMA, 'player': player, 'operation_id': operation_id, 'request_digest': fingerprint}


def resolve(journal, reference):
    reference = validate(reference)
    snapshot = journal.event_snapshot(reference['player'], reference['operation_id'])
    if snapshot is None:
        raise JournalError('referenced event is missing')
    if make(reference['player'], reference['operation_id'], snapshot.request) != reference:
        raise JournalError('referenced event request differs')
    return snapshot
