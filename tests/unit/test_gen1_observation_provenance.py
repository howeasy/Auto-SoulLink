"""Frame origins bind staged semantics to their one atomic containing event."""

import copy
import secrets

import pytest

from server import gen1_engine_signal_runtime as engine, gen1_inventory_observation as inventory
from server.event_reference import make
from server.gen1_frame_runtime import COMPONENT, complete, reserve
from server.gen1_observation_provenance import semantic_receipt, stage_origin
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit import test_gen1_frame_runtime as frame_fixtures
from tests.unit.test_gen1_frame_runtime import proof, returned
from tests.unit.test_gen1_starter_settlement import source_and_checkpoint

frame_setup = frame_fixtures.setup


@pytest.fixture
def prepared(frame_setup):
    runtime, document = frame_setup
    stage = runtime.state()
    reserve(document, 'a', proof(document))
    receipt, bundle = returned(runtime, document)
    closed = complete(document, 'a', receipt, bundle)
    request = {'event': 'frame_complete', 'receipt': receipt, 'bundle': bundle}
    operation = secrets.token_hex(16)
    origin = make('a', operation, request)
    return runtime, stage, document, request, operation, origin, closed


def semantic_request(document, request, kind):
    if kind == 'engine_signals':
        return {'event': kind, 'payload': copy.deepcopy(request['bundle']['engine_signals'])}
    initial = document['components']['gen1-initial-observations']['a']
    return {'event': kind, 'payload': {'sequence': 1, 'previous_operation_id': initial['operation_id'],
                                     'observation': copy.deepcopy(request['bundle']['inventory'])}}


def stage_pair(prepared):
    runtime, stage, document, request, operation, origin, closed = prepared
    engine_result = engine.stage_observation(
        runtime, stage, document, 'a', operation, semantic_request(document, request, 'engine_signals'),
        frame_origin=origin, frame_request=request,
    )
    inventory_result = inventory.stage_observation(
        runtime, stage, document, 'a', operation, semantic_request(document, request, 'inventory_observation'),
        frame_origin=origin, frame_request=request,
    )
    result = {'ack': 'ACK', 'ordinary_execution': False, 'closed_frame_digest': digest(closed),
              'observations_settled': True, 'engine_evidence_digest': engine_result['result']['engine_evidence_digest'],
              'inventory_transition_digest': inventory_result['result']['inventory_transition_digest']}
    return engine_result, inventory_result, result


def test_compound_semantic_views_resolve_outer_revision_commands_and_digests(prepared):
    runtime, stage, document, request, operation, origin, _ = prepared
    before = runtime.journal._db.total_changes
    source, checkpoint, result = stage_pair(prepared)
    assert runtime.journal._db.total_changes == before
    assert source['entry']['frame_origin'] == checkpoint['entry']['frame_origin'] == origin
    receipt = runtime.journal.commit('a', operation, request, expected_revision=stage.journal_revision,
                                    state=document, commands={'a': [], 'b': [{'cmd': 'fixture'}]},
                                    result=result, records=source['records'] + checkpoint['records'])
    for kind, value in [('engine_signals', source), ('inventory_observation', checkpoint)]:
        view = semantic_receipt(runtime.journal, 'a', value['entry'], kind)
        assert view.result == value['result']
        assert view.revision == receipt.revision and view.command_ids == receipt.command_ids


@pytest.mark.parametrize('fault', ['player', 'operation', 'digest', 'receipt', 'bundle-digest',
                                 'no-closure', 'active-trade', 'source', 'inventory'])
def test_forged_origin_or_closed_bundle_refuses_before_publication(prepared, fault):
    runtime, stage, document, request, operation, origin, _ = prepared
    semantic = semantic_request(document, request, 'engine_signals')
    if fault == 'player':
        origin['player'] = 'b'
    elif fault == 'operation':
        origin['operation_id'] = 'f' * 32
    elif fault == 'digest':
        origin['request_digest'] = 'f' * 64
    elif fault == 'receipt':
        request['receipt']['steps'] += 1
        origin = make('a', operation, request)
    elif fault == 'bundle-digest':
        document['components'][COMPONENT]['a']['pending_observation']['bundle_digest'] = 'f' * 64
    elif fault == 'no-closure':
        document['components'][COMPONENT]['a']['pending_observation'] = None
    elif fault == 'active-trade':
        document['active_trade'] = {'fixture': True}
    elif fault == 'source':
        semantic['payload']['sequence'] += 1
    else:
        semantic = semantic_request(document, request, 'inventory_observation')
        semantic['payload']['observation']['frame'] += 1
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError):
        stage_origin(document, 'a', operation, semantic, frame_origin=origin, frame_request=request)
    assert runtime.journal.snapshot() == before


@pytest.mark.parametrize('kind', ['engine_signals', 'inventory_observation'])
def test_frame_accounted_player_cannot_publish_standalone_observation(prepared, kind):
    runtime, stage, document, request, operation, _, _ = prepared
    module = engine if kind == 'engine_signals' else inventory
    with pytest.raises(JournalError, match='compound frame origin'):
        module.stage_observation(runtime, stage, document, 'a', operation, semantic_request(document, request, kind))


def test_valid_origin_allows_queued_commands_and_same_physical_reconnect(prepared, monkeypatch):
    runtime, _, _, _, _, _, _ = prepared
    metadata = copy.deepcopy(runtime.gate.sessions['a'].metadata)
    metadata['control_binding'].update(session_id='c' * 32, admission_epoch='d' * 32, binding_digest='e' * 64)
    runtime.gate.sessions['a'].metadata = metadata
    monkeypatch.setattr(runtime.journal, 'pending_ids', lambda player: ('f' * 32,))
    source, checkpoint, _ = stage_pair(prepared)
    assert source['entry']['frame_origin'] == checkpoint['entry']['frame_origin']


def test_origin_is_attached_before_starter_source_and_settlement_copies(frame_setup, monkeypatch):
    runtime, document = frame_setup
    stage = runtime.state()
    initial = document['components']['gen1-initial-observations']['a']
    source, checkpoint = source_and_checkpoint(runtime, 'a', initial['observation'], initial['operation_id'])
    reserve(document, 'a', proof(document))
    receipt, bundle = returned(runtime, document)
    bundle.update(inventory=checkpoint['observation'], engine_signals=source)
    receipt.update(after=checkpoint['observation']['frame'], steps=10, observations_digest=digest(bundle))
    complete(document, 'a', receipt, bundle)
    request = {'event': 'frame_complete', 'receipt': receipt, 'bundle': bundle}
    operation = secrets.token_hex(16)
    origin = make('a', operation, request)
    monkeypatch.setattr(runtime.journal, 'pending_ids', lambda player: ('f' * 32,))
    engine.stage_observation(runtime, stage, document, 'a', operation, {'event': 'engine_signals', 'payload': source},
                             frame_origin=origin, frame_request=request)
    inventory.stage_observation(runtime, stage, document, 'a', operation,
                                {'event': 'inventory_observation', 'payload': checkpoint},
                                frame_origin=origin, frame_request=request)
    component = document['components']['gen1-starter-settlement']
    assert component['sources']['a']['engine_record']['frame_origin'] == origin
    assert component['settled']['a']['inventory_entry']['frame_origin'] == origin


@pytest.mark.parametrize('fault', ['unsettled', 'bad-digest', 'missing-digest', 'extra', 'changed-entry', 'foreign-player'])
def test_outer_event_must_prove_exact_settled_semantics(prepared, fault):
    runtime, stage, document, request, operation, _, _ = prepared
    source, checkpoint, result = stage_pair(prepared)
    if fault == 'unsettled':
        result['observations_settled'] = False
    elif fault == 'bad-digest':
        result['engine_evidence_digest'] = 'f' * 64
    elif fault == 'missing-digest':
        del result['inventory_transition_digest']
    elif fault == 'extra':
        result['permission'] = True
    runtime.journal.commit('a', operation, request, expected_revision=stage.journal_revision,
                           state=document, commands={'a': [], 'b': []}, result=result)
    entry = source['entry']
    if fault == 'changed-entry':
        entry['transactions'] = []
    with pytest.raises(JournalError):
        semantic_receipt(runtime.journal, 'b' if fault == 'foreign-player' else 'a', entry, 'engine_signals')


def test_standalone_receipt_lookup_keeps_legacy_replay_semantics(prepared):
    runtime, stage, document, request, operation, _, _ = prepared
    del document['components'][COMPONENT]
    value = engine.stage_observation(runtime, stage, document, 'a', operation,
                                     semantic_request(document, request, 'engine_signals'))
    semantic = {'event': 'engine_signals', 'payload': value['entry']['payload']}
    expected = runtime.journal.commit('a', operation, semantic, expected_revision=stage.journal_revision,
                                      state=document, commands=value['commands'], result=value['result'])
    assert semantic_receipt(runtime.journal, 'a', value['entry'], 'engine_signals') == expected
    with pytest.raises(JournalError, match='reused'):
        runtime.journal.event('a', operation, {'event': 'changed'})


def test_inventory_only_frame_has_no_invented_engine_evidence(frame_setup):
    runtime, document = frame_setup
    stage = runtime.state()
    reserve(document, 'a', proof(document))
    receipt, bundle = returned(runtime, document)
    bundle['engine_signals'] = None
    receipt['observations_digest'] = digest(bundle)
    closed = complete(document, 'a', receipt, bundle)
    request = {'event': 'frame_complete', 'receipt': receipt, 'bundle': bundle}
    operation = secrets.token_hex(16)
    origin = make('a', operation, request)
    staged = inventory.stage_observation(
        runtime, stage, document, 'a', operation, semantic_request(document, request, 'inventory_observation'),
        frame_origin=origin, frame_request=request,
    )
    result = {'ack': 'ACK', 'ordinary_execution': False, 'closed_frame_digest': digest(closed),
              'observations_settled': True, 'inventory_transition_digest': digest(staged['entry'])}
    runtime.journal.commit('a', operation, request, expected_revision=stage.journal_revision,
                           state=document, commands=staged['commands'], result=result, records=staged['records'])
    assert semantic_receipt(runtime.journal, 'a', staged['entry'], 'inventory_observation').result == staged['result']
