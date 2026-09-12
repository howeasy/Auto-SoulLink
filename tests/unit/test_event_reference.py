"""An event reference identifies checked evidence and grants no authority."""

import copy

import pytest

from server.event_reference import make, resolve, validate
from server.protocol import digest
from server.protocol_journal import JournalError, ProtocolJournal

OPERATION = 'a' * 32
REQUEST = {'event': 'observation', 'payload': {'value': [1]}}


@pytest.fixture
def journal(tmp_path):
    instance = ProtocolJournal(tmp_path / 'events.sqlite3', contract_hash='b' * 64)
    instance.bootstrap({})
    instance.commit('a', OPERATION, REQUEST, expected_revision=0, state={},
                    commands={'a': [], 'b': []}, result={'ack': 'ACK'})
    try:
        yield instance
    finally:
        instance.close()


def test_reference_resolves_detached_snapshot_without_writes(journal):
    reference = make('a', OPERATION, REQUEST)
    assert reference == {'schema': 'slink-event-reference-v1', 'player': 'a',
                         'operation_id': OPERATION, 'request_digest': digest(REQUEST)}
    changes = journal._db.total_changes
    snapshot = resolve(journal, reference)
    assert snapshot == journal.event_snapshot('a', OPERATION)
    snapshot.request['payload']['value'].append(2)
    assert resolve(journal, reference).request == REQUEST
    assert journal._db.total_changes == changes
    detached = validate(reference)
    detached['player'] = 'b'
    assert reference['player'] == 'a'


@pytest.mark.parametrize('fault', ['schema', 'player', 'operation', 'digest', 'extra', 'missing'])
def test_malformed_reference_refuses(journal, fault):
    reference = make('a', OPERATION, REQUEST)
    if fault == 'schema':
        reference['schema'] = 'other'
    elif fault == 'player':
        reference['player'] = 'c'
    elif fault == 'operation':
        reference['operation_id'] = 'A' * 32
    elif fault == 'digest':
        reference['request_digest'] = True
    elif fault == 'extra':
        reference['authority'] = True
    else:
        del reference['request_digest']
    with pytest.raises(JournalError):
        resolve(journal, reference)


@pytest.mark.parametrize('fault', ['wrong-player', 'missing-operation', 'changed-request', 'corrupt-request', 'corrupt-result'])
def test_missing_foreign_or_corrupt_event_refuses(journal, fault):
    reference = make('a', OPERATION, REQUEST)
    if fault == 'wrong-player':
        reference['player'] = 'b'
    elif fault == 'missing-operation':
        reference['operation_id'] = 'c' * 32
    elif fault == 'changed-request':
        changed = copy.deepcopy(REQUEST)
        changed['payload']['value'] = [2]
        reference = make('a', OPERATION, changed)
    else:
        column = 'request' if fault == 'corrupt-request' else 'result'
        journal._db.execute(f"UPDATE events SET {column}='{{}}'")
    with pytest.raises(JournalError):
        resolve(journal, reference)


@pytest.mark.parametrize('player,operation,message', [
    pytest.param('c', OPERATION, REQUEST, id='bad-player'),
    pytest.param('a', 'bad', REQUEST, id='bad-operation'),
    pytest.param('a', OPERATION, [], id='not-object'),
    pytest.param('a', OPERATION, {'bad': object()}, id='not-json'),
])
def test_make_requires_valid_identifiers_and_bounded_json(player, operation, message):
    with pytest.raises(JournalError):
        make(player, operation, message)
